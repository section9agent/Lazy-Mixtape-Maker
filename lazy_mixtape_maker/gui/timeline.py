"""The timeline: songs laid out like two DJ decks, transitions as shaded overlaps,
effects as small markers. Drag a song sideways to change how long it blends with
the previous one, drag its left or right edge to trim where it starts or ends, drag an effect to retime it."""
from __future__ import annotations

import colorsys

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import plan as planmod
from ..audio_io import SR
from ..plan import timeline as build_timeline
from .state import AppState

RULER_H = 26
LANE_H = 86
LANE_GAP = 30
TOP_PAD = 8
EDGE = 8  # px grab zone on a song's left / right edge
SEC_H = 15  # height of the song-section strip

SECTION_COLORS = {
    "intro": "#5aa9e6", "verse": "#7fc8a9", "chorus": "#f2a541", "bridge": "#c77dff",
    "outro": "#9aa0a6", "break": "#e76f51", "drop": "#ef476f",
}
FX_COLORS = {
    "echo": "#4cc9f0", "delay": "#4895ef", "reverb": "#b388eb", "filter": "#ffd166",
    "flange": "#06d6a0", "backspin": "#ef476f", "cut": "#ff9f1c", "stutter": "#2ec4b6",
}


def track_color(i: int, selected: bool) -> QColor:
    h = (i * 0.137 + 0.58) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.42, 0.62 if not selected else 0.82)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


class TimelineWidget(QWidget):
    seek = Signal(float)

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.pps = 6.0                # pixels per second
        self.playhead = 0.0
        self._drag = None
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER_H + TOP_PAD + 2 * LANE_H + LANE_GAP + 22)
        state.changed.connect(self._refresh)
        state.selection.connect(self.update)

    # ------------------------------------------------------------------ geometry
    def total_seconds(self) -> float:
        slots = build_timeline(self.state.plan)
        return (slots[-1].end / SR + 8.0) if slots else 60.0

    def _refresh(self):
        self.setMinimumWidth(int(self.total_seconds() * self.pps) + 60)
        self.update()

    def set_zoom(self, pps: float):
        self.pps = max(1.0, min(80.0, pps))
        self._refresh()

    def fit_to(self, width: int):
        self.set_zoom(max(1.0, (width - 70) / max(10.0, self.total_seconds())))

    def set_playhead(self, seconds: float):
        self.playhead = seconds
        self.update()

    def _lane_y(self, i: int) -> float:
        return RULER_H + TOP_PAD + (i % 2) * (LANE_H + LANE_GAP)

    def _rects(self):
        plan = self.state.plan
        slots = build_timeline(plan)
        out = []
        for i, s in enumerate(slots):
            x = s.start / SR * self.pps + 20
            w = s.length / SR * self.pps
            out.append(QRectF(x, self._lane_y(i), max(2.0, w), LANE_H))
        return slots, out

    def _fx_rect(self, i: int, e, slot, rect: QRectF) -> QRectF:
        n = slot.length / SR
        start = e.offset if e.anchor == "start" else n + e.offset
        x = rect.left() + start * self.pps
        return QRectF(x, rect.bottom() + 3, max(6.0, e.duration * self.pps), 12)

    # ------------------------------------------------------------------- painting
    def paintEvent(self, ev):
        st = self.state
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1d23"))
        self._paint_ruler(p)
        if not st.plan.tracks:
            p.setPen(QColor("#8b93a1"))
            p.setFont(QFont(self.font().family(), 11))
            p.drawText(self.rect().adjusted(0, RULER_H, 0, 0), Qt.AlignmentFlag.AlignCenter,
                       "Add songs (drag them in, or use Add songs…) and the mix will appear here")
            return
        slots, rects = self._rects()
        plan = st.plan
        # transitions first, behind the songs
        for i, s in enumerate(slots):
            if i and s.overlap_in > 0 and s.trans_in:
                x0 = rects[i].left()
                w = s.overlap_in / SR * self.pps
                r = QRectF(x0, RULER_H + 2, w, 2 * LANE_H + LANE_GAP + TOP_PAD * 2)
                p.fillRect(r, QColor(255, 255, 255, 22))
                p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(r.left(), r.top()), QPointF(r.left(), r.bottom()))
                p.drawLine(QPointF(r.right(), r.top()), QPointF(r.right(), r.bottom()))
                p.setPen(QColor(220, 225, 235, 190))
                p.setFont(QFont(self.font().family(), 8))
                p.drawText(QRectF(r.left(), r.bottom() - 16, max(w, 70), 14), Qt.AlignmentFlag.AlignLeft,
                           f" {s.trans_in.type.replace('_', ' ')}")
        for i, (t, s, r) in enumerate(zip(plan.tracks, slots, rects)):
            self._paint_track(p, i, t, s, r)
        # playhead
        x = self.playhead * self.pps + 20
        p.setPen(QPen(QColor("#ff5d73"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))

    def _paint_ruler(self, p: QPainter):
        p.fillRect(0, 0, self.width(), RULER_H, QColor("#23262e"))
        step = 5
        for cand in (1, 2, 5, 10, 15, 30, 60, 120, 300):
            if cand * self.pps >= 60:
                step = cand
                break
        else:
            step = 600
        p.setFont(QFont(self.font().family(), 8))
        t = 0
        while t * self.pps + 20 < self.width():
            x = t * self.pps + 20
            p.setPen(QColor("#4a4f5c"))
            p.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
            p.setPen(QColor("#9aa3b2"))
            p.drawText(QPointF(x + 3, RULER_H - 11), f"{int(t // 60)}:{int(t % 60):02d}")
            t += step

    def _paint_track(self, p: QPainter, i, t, slot, rect: QRectF):
        st = self.state
        an = st.lib[t.song_id]
        sel = i == st.sel
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.fillPath(path, QBrush(track_color(i, sel)))
        p.save()
        p.setClipPath(path)
        # waveform (near-black, over the track colour)
        self._paint_wave(p, an, t, slot, rect)
        # section strip (intro / verse / chorus ...)
        for sec in an.sections:
            a = max(sec.start, t.src_start)
            b = min(sec.end, t.src_end)
            if b <= a:
                continue
            x0 = rect.left() + float(slot.curve.mix_time(a)) * self.pps
            x1 = rect.left() + float(slot.curve.mix_time(b)) * self.pps
            col = QColor(SECTION_COLORS.get(sec.label, "#aaaaaa"))
            band = QRectF(x0, rect.bottom() - SEC_H, x1 - x0, SEC_H)
            p.fillRect(band, col)
            p.setPen(QPen(QColor(10, 10, 14, 200), 1))
            p.drawLine(QPointF(x0, band.top()), QPointF(x0, band.bottom()))
            if x1 - x0 > 30:
                p.setPen(QColor(10, 10, 14))
                f = QFont(self.font().family(), 8)
                f.setBold(True)
                p.setFont(f)
                p.drawText(band.adjusted(4, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           p.fontMetrics().elidedText(sec.label, Qt.TextElideMode.ElideRight, int(band.width() - 6)))
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)     # the previous track's effect boxes leave a brush behind; it filled over the waveform
        p.setPen(QPen(QColor("#ffffff") if sel else QColor(0, 0, 0, 90), 2 if sel else 1))
        p.drawPath(path)
        # labels (white with a dark shadow so they read over the waveform)
        f = QFont(self.font().family(), 9)
        f.setBold(True)
        p.setFont(f)
        label = f"{i + 1}. {an.title}"
        lab = p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(rect.width() - 16))
        for dx, col in ((1, QColor(0, 0, 0, 200)), (0, QColor("#ffffff"))):
            p.setPen(col)
            p.drawText(rect.adjusted(8 + dx, 5 + dx, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, lab)
        p.setFont(QFont(self.font().family(), 8))
        sub = f"{an.artist + '  ·  ' if an.artist else ''}{an.camelot}  ·  {(t.bpm or self.state.plan.master_bpm):.0f} BPM"
        if t.pitch:
            sub += f"  ·  {t.pitch:+d} st"
        if i == st.sel or rect.width() > 150:
            subt = p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, int(rect.width() - 16))
            for dx, col in ((1, QColor(0, 0, 0, 200)), (0, QColor(235, 238, 245))):
                p.setPen(col)
                p.drawText(rect.adjusted(8 + dx, 22 + dx, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, subt)
        if t.song_id not in st.paths:
            p.setPen(QColor("#ff8a8a"))
            p.drawText(rect.adjusted(8, 38, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "file not found")
        # effects
        for e in t.effects:
            fr = self._fx_rect(i, e, slot, rect)
            col = QColor(FX_COLORS.get(e.type, "#cccccc"))
            fx_sel = e.id == st.sel_fx
            tr_fx = slot.trans_in if e.anchor == "start" else slot.trans_out
            muted = bool(tr_fx and not tr_fx.fx)
            p.setBrush(QColor(90, 94, 104, 120) if muted else (col if fx_sel else QColor(col.red(), col.green(), col.blue(), 210)))
            p.setPen(QPen(QColor("#ffffff"), 2) if fx_sel else QPen(QColor(0, 0, 0, 120), 1))
            p.drawRoundedRect(fr, 3, 3)
            if fr.width() > 30:
                p.setPen(QColor("#9aa0a6") if muted else QColor("#101015"))
                p.setFont(QFont(self.font().family(), 7))
                p.drawText(fr, Qt.AlignmentFlag.AlignCenter, e.type + (" (off)" if muted and fr.width() > 70 else ""))

    def _paint_wave(self, p: QPainter, an, t, slot, rect: QRectF):
        clip = p.clipBoundingRect()
        x0 = max(rect.left(), clip.left() - 2)
        x1 = min(rect.right(), clip.right() + 2)
        if x1 <= x0:
            return
        top, bot = rect.top() + 3, rect.bottom() - SEC_H - 2
        mid, half = (top + bot) / 2, (bot - top) / 2
        xs = np.arange(int(x0), int(x1) + 1, dtype=np.float64)
        u0 = (xs - rect.left()) / self.pps
        wave = an.wave
        step = an.wave_step or 0.1
        if wave:
            w = np.asarray(wave, dtype=np.float64) / 100.0
            amp = np.zeros(len(xs))
            for k in range(3):                  # a few samples per pixel so peaks survive zooming out
                src = slot.curve.src_time(u0 + k / (3.0 * self.pps))
                idx = np.clip((src / step).astype(int), 0, len(w) - 1)
                amp = np.maximum(amp, w[idx])
        elif an.bar_energy:
            be = np.asarray(an.bar_energy, dtype=np.float64)
            src = slot.curve.src_time(u0)
            idx = np.clip(((src - an.bar_energy_origin) / an.bar_length).astype(int), 0, len(be) - 1)
            amp = 0.15 + 0.6 * be[idx]
        else:
            return
        poly = QPainterPath()
        poly.moveTo(xs[0], mid)
        for x, a in zip(xs, amp):
            poly.lineTo(x, mid - a * half)
        for x, a in zip(xs[::-1], amp[::-1]):
            poly.lineTo(x, mid + a * half)
        poly.closeSubpath()
        p.fillPath(poly, QColor(8, 8, 12, 204))

    # --------------------------------------------------------------- interaction
    def _hit(self, pos):
        """-> ('fx', i, effect) | ('edge', i) right edge | ('edge_l', i) left edge | ('track', i) | None"""
        slots, rects = self._rects()
        plan = self.state.plan
        for i in reversed(range(len(rects))):
            for e in plan.tracks[i].effects:
                if self._fx_rect(i, e, slots[i], rects[i]).contains(pos):
                    return ("fx", i, e)
        for i in reversed(range(len(rects))):
            r = rects[i]
            if r.contains(pos):
                if pos.x() > r.right() - EDGE:
                    return ("edge", i)
                if pos.x() < r.left() + EDGE:
                    return ("edge_l", i)
                return ("track", i)
        return None

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            hit = self._hit(pos)
            if hit and hit[0] in ("edge", "edge_l"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif hit and hit[0] in ("track", "fx"):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            return
        d = self._drag
        dsec = (pos.x() - d["x0"]) / self.pps
        st = self.state
        plan = st.plan
        try:
            if d["kind"] == "track" and d["i"] > 0:
                beat = 60.0 / planmod.tr_tempo(plan, plan.transition_after(d["i"] - 1))
                db = round(dsec / beat)
                beats = max(0, d["beats0"] - db)

                def fn(p, lib):
                    tr = p.transition_after(d["i"] - 1)
                    new_type = tr.type
                    if beats > 0 and tr.type in ("cut", "cut_fx"):
                        new_type = "crossfade" if beats < 16 else "eq_swap"
                    planmod.set_transition(p, lib, d["i"] - 1, new_type, beats)
                st.edit(fn)
            elif d["kind"] == "edge":
                t = plan.tracks[d["i"]]
                beat = 60.0 / (t.bpm or plan.master_bpm)
                db = round(dsec / beat)
                an = st.lib[t.song_id]
                new_end = min(an.duration, d["end0"] + db * beat * (t.rate_out or t.rate))
                st.edit(lambda p, lib: planmod.set_track_bounds(p, lib, d["i"], src_end=new_end))
            elif d["kind"] == "edge_l":
                i = d["i"]
                t = plan.tracks[i]
                an = st.lib[t.song_id]
                if i > 0:
                    beat = 60.0 / planmod.tr_tempo(plan, plan.transition_after(i - 1))
                    rate = t.rate_in or t.rate
                else:
                    beat, rate = 60.0 / (t.bpm or plan.master_bpm), t.rate
                step = beat * rate
                want = d["start0"] + round(dsec / beat) * step
                new_start = min(max(0.0, want), t.src_end - 2.0)
                db = round((new_start - d["start0"]) / step)          # beats the edge really moved
                new_start = d["start0"] + db * step
                beats = max(0, d["beats0"] - db) if i > 0 else 0

                def fn(p, lib):
                    if i > 0:
                        tr = p.transition_after(i - 1)
                        new_type = tr.type
                        if beats > 0 and tr.type in ("cut", "cut_fx"):
                            new_type = "crossfade" if beats < 16 else "eq_swap"
                        planmod.set_transition(p, lib, i - 1, new_type, beats)
                    planmod.set_track_bounds(p, lib, i, src_start=new_start)
                st.edit(fn)
            elif d["kind"] == "fx":
                beat = 60.0 / (plan.tracks[d["i"]].bpm or plan.master_bpm)
                q = beat / 4
                off = d["off0"] + round(dsec / q) * q
                e = d["fx"]
                off = max(0.0, off) if e.anchor == "start" else min(0.5 * beat, off)
                st.edit(lambda p, lib: planmod.update_effect(p, d["i"], e.id, offset=float(off)))
        except (ValueError, KeyError, IndexError):
            pass

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        st = self.state
        if pos.y() < RULER_H:
            self.seek.emit(max(0.0, (pos.x() - 20) / self.pps))
            return
        hit = self._hit(pos)
        if not hit:
            st.select(-1)
            self.seek.emit(max(0.0, (pos.x() - 20) / self.pps))
            return
        i = hit[1]
        plan = st.plan
        t = plan.tracks[i]
        d = {"kind": hit[0], "i": i, "x0": pos.x()}
        if hit[0] == "fx":
            d.update(fx=hit[2], off0=hit[2].offset)
            st.select(i, hit[2].id)
        else:
            tr = plan.transition_after(i - 1) if i > 0 else None
            d.update(beats0=tr.overlap_beats if tr else 0, end0=t.src_end, start0=t.src_start)
            st.select(i)
        st.begin_gesture()
        self._drag = d
        self.setCursor(Qt.CursorShape.SizeHorCursor if hit[0] in ("edge", "edge_l") else Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            self.state.end_gesture()
            self.unsetCursor()

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.pps * (1.15 if ev.angleDelta().y() > 0 else 1 / 1.15))
            ev.accept()
        else:
            ev.ignore()
