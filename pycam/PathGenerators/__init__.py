# -*- coding: utf-8 -*-
"""
$Id$

Copyright 2008 Lode Leroy

This file is part of PyCAM.

PyCAM is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

PyCAM is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with PyCAM.  If not, see <http://www.gnu.org/licenses/>.
"""

__all__ = ["DropCutter", "PushCutter"]

from pycam.Geometry.utils import INFINITE, epsilon
from pycam.Geometry import Point
import math


class Hit:
    def __init__(self, cl, t, d, dir):
        self.cl = cl
        self.t = t
        self.d = d
        self.dir = dir
        self.z = -INFINITE

    def cmp(a,b):
        return cmp(a.d, b.d)

def get_free_horizontal_paths_triangles(model, cutter, minx, maxx, miny, maxy, z):
    points = []
    x_dist = abs(maxx - minx)
    y_dist = abs(maxy - miny)
    xy_dist = math.sqrt(x_dist * x_dist + y_dist * y_dist)
    x_frac = x_dist / xy_dist
    y_frac = y_dist / xy_dist
    forward = Point(x_frac, y_frac, 0)
    backward = Point(-x_frac, -y_frac, 0)
    forward_small = Point(epsilon * x_frac, epsilon * y_frac, 0)
    backward_small = Point(-epsilon * x_frac, -epsilon * y_frac, 0)

    # find all hits along scan line
    hits = []
    prev = Point(minx, miny, z)
    hits.append(Hit(prev, None, 0, None))

    triangles = model.triangles(minx - cutter.radius, miny - cutter.radius, z,
            maxx + cutter.radius, maxy + cutter.radius, INFINITE)

    for t in triangles:
        # normals point outward... and we want to approach the model from the outside!
        n = t.normal().dot(forward)
        cutter.moveto(prev)
        if n >= 0:
            (cl, d) = cutter.intersect(backward, t)
            if cl:
                hits.append(Hit(cl, t, -d, backward))
                hits.append(Hit(cl.sub(backward_small), t, -d + epsilon, backward))
                hits.append(Hit(cl.add(backward_small), t, -d - epsilon, backward))
        if n <= 0:
            (cl, d) = cutter.intersect(forward, t)
            if cl:
                hits.append(Hit(cl, t, d, forward))
                hits.append(Hit(cl.add(forward_small), t, d + epsilon, forward))
                hits.append(Hit(cl.sub(forward_small), t, d - epsilon, forward))

    next = Point(maxx, maxy, z)
    hits.append(Hit(next, None, xy_dist, None))


    # sort along the scan direction
    hits.sort(Hit.cmp)

    # remove duplicates (typically shared edges)
    i = 1
    while i < len(hits):
        while i<len(hits) and abs(hits[i].d - hits[i-1].d)<epsilon/2:
            del hits[i]
        i += 1

    # determine height at each interesting point
    for h in hits:
        (zmax, tmax) = drop_cutter_test(cutter, h.cl, model)
        h.z = zmax

    # find first hit cutter location that is below z-level
    begin = hits[0].cl
    end = None
    for h in hits:
        if h.z >= z - epsilon/10:
            if begin and end:
                points.append(begin)
                points.append(end)
            begin = None
            end = None
        if h.z <= z + epsilon/10:
            if not begin:
                begin = h.cl
            else:
                end = h.cl
        
    # add add possibly remaining couple from the previous loop
    if begin and end:
        points.append(begin)
        points.append(end)

    return points


def get_free_horizontal_paths_ode(physics, minx, maxx, miny, maxy, z, depth=8):
    """ Recursive function for splitting a line (usually along x or y) into
    small pieces to gather connected paths for the PushCutter.
    Strategy: check if the whole line is free (without collisions). Do a
    recursive call (for the first and second half), if there was a
    collision.

    Usually either minx/maxx or miny/maxy should be equal, unless you want
    to do a diagonal cut.
    @param minx: lower limit of x
    @type minx: float
    @param maxx: upper limit of x; should equal minx for a cut along the x axis
    @type maxx: float
    @param miny: lower limit of y
    @type miny: float
    @param maxy: upper limit of y; should equal miny for a cut along the y axis
    @type maxy: float
    @param z: the fixed z level
    @type z: float
    @param depth: number of splits to be calculated via recursive calls; the
        accuracy can be calculated as (maxx-minx)/(2^depth)
    @type depth: int
    @returns: a list of points that describe the tool path of the PushCutter;
        each pair of points defines a collision-free path
    @rtype: list(pycam.Geometry.Point.Point)
    """
    points = []
    # "resize" the drill along the while x/y range and check for a collision
    physics.extend_drill(maxx-minx, maxy-miny, 0.0)
    physics.set_drill_position((minx, miny, z))
    if physics.check_collision():
        # collision detected
        if depth > 0:
            middle_x = (minx + maxx)/2.0
            middle_y = (miny + maxy)/2.0
            group1 = get_free_horizontal_paths_ode(physics, minx, middle_x,
                    miny, middle_y, z, depth-1)
            group2 = get_free_horizontal_paths_ode(physics, middle_x, maxx,
                    middle_y, maxy, z, depth-1)
            if group1 and group2 and (group1[-1].x == group2[0].x) and (group1[-1].y == group2[0].y):
                # the last couple of the first group ends where the first couple of the second group starts
                # we will combine them into one couple
                last = group1[-2]
                first = group2[1]
                combined = [last, first]
                points.extend(group1[:-2])
                points.extend(combined)
                points.extend(group2[2:])
            else:
                # the two groups are not connected - just add both
                points.extend(group1)
                points.extend(group2)
        else:
            # no points to be added
            pass
    else:
        # no collision - the line is free
        points.append(Point(minx, miny, z))
        points.append(Point(maxx, maxy, z))
    physics.reset_drill()
    return points

def drop_cutter_test(cutter, point, model):
    zmax = -INFINITE
    tmax = None
    cutter.moveto(point)
    for t in model.triangles():
        if t.normal().z < 0: continue
        cl = cutter.drop(t)
        if cl and cl.z > zmax and cl.z < INFINITE:
            zmax = cl.z
            tmax = t
    return (zmax, tmax)

