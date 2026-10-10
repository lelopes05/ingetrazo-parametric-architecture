# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression: a selected wall overlay must never send gigantic values to Qt."""
import math
import unittest

from OpenTrace_BIM.overlay_safety import visible_pixel, visible_segment


class FakeViewport:
    def width(self): return 800
    def height(self): return 600
    def _world_to_pixel(self, p): return (p[0], p[1])
    def _clip_segment_front(self, a, b): return (a, b)
    def _clip_pixel_line(self, p0, p1, margin=32.0):
        x0,y0=p0
        x1,y1=p1
        dx,dy=x1-x0,y1-y0
        lo,hi=0.0,1.0
        for p,q in ((-dx,x0+margin),(dx,800+margin-x0),
                    (-dy,y0+margin),(dy,600+margin-y0)):
            if p==0:
                if q<0:return None
                continue
            t=q/p
            if p<0:lo=max(lo,t)
            else:hi=min(hi,t)
            if lo>hi:return None
        return ((x0+lo*dx,y0+lo*dy),(x0+hi*dx,y0+hi*dy))


class SafeOverlayTests(unittest.TestCase):
    def test_extreme_world_projections_are_clipped_before_painting(self):
        vp=FakeViewport()
        line=visible_segment(vp,(-10**9,250),(10**9,350))
        self.assertIsNotNone(line)
        for point in line:
            self.assertTrue(all(math.isfinite(v) for v in point))
            self.assertLessEqual(abs(point[0]),832)
            self.assertLessEqual(abs(point[1]),632)

    def test_offscreen_hotspots_are_not_drawn(self):
        vp=FakeViewport()
        self.assertIsNone(visible_pixel(vp,(10**12,10**12)))
        self.assertIsNone(visible_pixel(vp,(float("inf"),123)))
        self.assertEqual(visible_pixel(vp,(400,250)),(400.0,250.0))

    def test_offscreen_segment_is_rejected(self):
        self.assertIsNone(visible_segment(FakeViewport(),(-1000,-1000),(-500,-500)))

    def test_fallback_without_host_pixel_clipper_remains_bounded(self):
        vp=FakeViewport()
        vp._clip_pixel_line=None
        seg=visible_segment(vp,(-1e8,100),(1e8,100))
        self.assertIsNotNone(seg)
        self.assertAlmostEqual(seg[0][0],-32)
        self.assertAlmostEqual(seg[1][0],832)


if __name__=="__main__":
    unittest.main()
