"""The timeline: songs laid out like two DJ decks, transitions as coloured overlaps with a badge above them,
effects as markers under each song.

Drag a transition's badge (or the song) sideways to change how long the songs blend; click the badge to edit it.
Drag a song's left or right edge to trim where it starts or ends. Drag an effect to move it, or its right end to
make it longer. With an effect selected, the arrow keys nudge it (Shift: a whole beat)."""
from __future__ import annotations

import colorsys

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .. import plan as planmod
from ..audio_io import SR
from ..plan import timeline as build_timeline
from .state import AppState

RULER_H = 26
BADGE_H = 22      # the row of transition badges under the ruler
TOP_PAD = BADGE_H + 8
LANE_H = 86
LANE_GAP = 34     # room for the first lane's effect markers
FX_H = 20         # effect marker height
FX_MIN_W = 30     # ...and its smallest width, so it's always easy to grab (and shows a 3-letter name)
FX_GRAB = 5       # extra px around an effect that still counts as grabbing it
FX_RESIZE = 7     # px at an effect's right end that change its length
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


TRANS_COLORS = {"eq_swap": "#4cc9f0", "crossfade": "#7ae582", "cut_fx": "#ffb454", "cut": "#ff6b6b"}
TRANS_SHORT = {"eq_swap": "bass swap", "crossfade": "crossfade", "cut_fx": "cut + fx", "cut": "cut",
               "stem_bass": "stems: bass", "stem_blend": "stems: blend", "stem_drums_first": "stems: drums first",
               "stem_drums_last": "stems: drums last", "stem_instrumental": "stems: instrumental",
               "stem_breakdown": "stems: breakdown", "stem_acapella_out": "stems: a cappella",
               "stem_mashup": "stems: mashup", "stem_vocal_in": "stems: vocal in"}
FX_SHORT = {"echo": "ECH", "delay": "DLY", "reverb": "REV", "filter": "FLT", "flange": "FLG", "backspin": "BSP",
            "cut": "CUT", "stutter": "STU"}


def trans_color(kind: str) -> QColor:
    return QColor(TRANS_COLORS.get(kind, "#c77dff"))          # every stem transition: purple


def track_color(i: int, selected: bool) -> QColor:
    h = (i * 0.137 + 0.58) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.42, 0.62 if not selected else 0.82)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


class TimelineWidget(QWidget):
    seek = Signal(float)
    transition_clicked = Signal(int)      # index of the song the transition comes after

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.pps = 6.0                # pixels per second
        self.playhead = 0.0
        self._drag = None
        self._hover = None                 # what the mouse is over: a key from _hit_key()
        self._readout = ""                 # live value shown while dragging
        self._readout_at = QPointF()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumHeight(RULER_H + TOP_PAD + 2 * LANE_H + LANE_GAP + FX_H + 12)
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
        return QRectF(x, rect.bottom() + 5, max(FX_MIN_W, e.duration * self.pps), FX_H)

    def _trans_zone(self, i: int, slot, rect: QRectF) -> QRectF:
        """The blend into song i: where it overlaps the song before (a thin strip for a cut)."""
        w = slot.overlap_in / SR * self.pps
        return QRectF(rect.left(), RULER_H + 2, max(w, 0.0), 2 * LANE_H + LANE_GAP + TOP_PAD)

    def _badge_text(self, tr) -> str:
        beats = "" if tr.type == "cut" else f" · {tr.overlap_beats}"
        return f"⟷ {TRANS_SHORT.get(tr.type, tr.type.replace('_', ' '))}{beats}"

    def _badge_rect(self, i: int, slot, rect: QRectF) -> QRectF:
        z = self._trans_zone(i, slot, rect)
        f = QFont(self.font().family(), 8)
        f.setBold(True)
        from PySide6.QtGui import QFontMetrics
        need = QFontMetrics(f).horizontalAdvance(self._badge_text(slot.trans_in)) + 22 if slot.trans_in else 96
        w = max(z.width(), float(need))
        return QRectF(z.center().x() - w / 2, RULER_H + 3, w, BADGE_H - 2)

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
        # transitions: a tint behind the songs...
        for i, s in enumerate(slots):
            if i and s.trans_in:
                z = self._trans_zone(i, s, rects[i])
                col = trans_color(s.trans_in.type)
                on = self._hover == ("trans", i) or (self._drag or {}).get("kind") in ("track", "trans") \
                    and (self._drag or {}).get("i") == i
                if z.width() > 0:
                    p.fillRect(z, QColor(col.red(), col.green(), col.blue(), 70 if on else 42))
        for i, (t, s, r) in enumerate(zip(plan.tracks, slots, rects)):
            self._paint_track(p, i, t, s, r)
        # ...and their edges and badges on top, so they read over the waveforms
        for i, s in enumerate(slots):
            if i and s.trans_in:
                self._paint_transition(p, i, s, rects[i])
        # playhead
        x = self.playhead * self.pps + 20
        p.setPen(QPen(QColor("#ff5d73"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        if self._readout and self._drag is not None:
            self._paint_readout(p)

    def _paint_transition(self, p: QPainter, i: int, slot, rect: QRectF):
        tr = slot.trans_in
        z = self._trans_zone(i, slot, rect)
        col = trans_color(tr.type)
        d = self._drag or {}
        on = self._hover == ("trans", i) or (d.get("kind") in ("track", "trans") and d.get("i") == i)
        sel = self.state.sel == i - 1
        edge = QColor(col)
        edge.setAlpha(255 if on or sel else 210)
        p.setPen(QPen(edge, 3 if on else 2))
        p.drawLine(QPointF(z.left(), z.top() + BADGE_H), QPointF(z.left(), z.bottom()))
        if z.width() > 0:
            p.drawLine(QPointF(z.right(), z.top() + BADGE_H), QPointF(z.right(), z.bottom()))
            band = QColor(col)
            band.setAlpha(230)
            for lane in (0, 1):                    # a coloured bar along the top of both songs where they blend
                y = self._lane_y(lane)
                p.fillRect(QRectF(z.left(), y, z.width(), 4), band)
        # the badge: what it is, how long, and a grip to drag
        br = self._badge_rect(i, slot, rect)
        path = QPainterPath()
        path.addRoundedRect(br, br.height() / 2, br.height() / 2)
        fill = QColor(col) if on or sel else QColor(col.red() // 2 + 20, col.green() // 2 + 20, col.blue() // 2 + 20)
        p.fillPath(path, fill)
        p.setPen(QPen(QColor("#ffffff") if sel else QColor(0, 0, 0, 140), 2 if sel else 1))
        p.drawPath(path)
        f = QFont(self.font().family(), 8)
        f.setBold(True)
        p.setFont(f)
        text = self._badge_text(tr)
        p.setPen(QColor("#101015") if on or sel else QColor("#f4f6fb"))
        p.drawText(br.adjusted(8, 0, -6, 0), Qt.AlignmentFlag.AlignCenter,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(br.width() - 14)))

    def _paint_readout(self, p: QPainter):
        f = QFont(self.font().family(), 9)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(self._readout) + 16, fm.height() + 8
        x = min(max(4.0, self._readout_at.x() + 14), self.width() - w - 4)
        y = max(RULER_H + 2.0, self._readout_at.y() - h - 10)
        r = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(r, 5, 5)
        p.fillPath(path, QColor(12, 13, 18, 235))
        p.setPen(QPen(QColor("#ff71ce"), 1))
        p.drawPath(path)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._readout)

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
        d = self._drag or {}
        for e in t.effects:
            fr = self._fx_rect(i, e, slot, rect)
            col = QColor(FX_COLORS.get(e.type, "#cccccc"))
            fx_sel = e.id == st.sel_fx
            hot = fx_sel or self._hover in (("fx", i, e.id), ("fx_len", i, e.id)) or d.get("fx") is e
            tr_fx = slot.trans_in if e.anchor == "start" else slot.trans_out
            muted = bool(tr_fx and not tr_fx.fx)
            # a thin line up into the song shows exactly where it starts
            line = QColor(col)
            line.setAlpha(120 if muted else 230 if hot else 170)
            p.setPen(QPen(line, 2 if hot else 1))
            p.drawLine(QPointF(fr.left(), rect.top() + 4), QPointF(fr.left(), fr.top()))
            path = QPainterPath()
            path.addRoundedRect(fr, 4, 4)
            p.fillPath(path, QColor(90, 94, 104, 150) if muted else (col.lighter(115) if hot else col))
            p.setPen(QPen(QColor("#ffffff"), 2) if fx_sel else QPen(QColor(255, 255, 255, 160), 1) if hot
                     else QPen(QColor(0, 0, 0, 150), 1))
            p.drawPath(path)
            if fr.width() >= 36 and not muted:      # the grip at its right end (drag it to make it longer)
                p.setPen(QPen(QColor(16, 16, 21, 150), 1))
                gx = fr.right() - 4
                p.drawLine(QPointF(gx, fr.top() + 5), QPointF(gx, fr.bottom() - 5))
                p.drawLine(QPointF(gx - 3, fr.top() + 5), QPointF(gx - 3, fr.bottom() - 5))
            f = QFont(self.font().family(), 8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#b9bec8") if muted else QColor("#101015"))
            name = e.type + (" (off)" if muted else "")
            label = name if p.fontMetrics().horizontalAdvance(name) < fr.width() - 14 else FX_SHORT.get(e.type, e.type[:3].upper())
            if p.fontMetrics().horizontalAdvance(label) > fr.width() - 4:
                label = label[:1].upper()
            p.drawText(fr.adjusted(2, 0, -5 if fr.width() >= 36 else -1, 0), Qt.AlignmentFlag.AlignCenter, label)

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
        """-> ('fx', i, effect) | ('fx_len', i, effect) its right end | ('trans', i) the badge / edge of the blend
        into song i | ('edge', i) right edge | ('edge_l', i) left edge | ('track', i) | None"""
        slots, rects = self._rects()
        plan = self.state.plan
        for i in reversed(range(len(rects))):
            for e in reversed(plan.tracks[i].effects):
                fr = self._fx_rect(i, e, slots[i], rects[i])
                if fr.adjusted(-FX_GRAB, -FX_GRAB, FX_GRAB, FX_GRAB).contains(pos):
                    if fr.width() >= 36 and pos.x() > fr.right() - FX_RESIZE:
                        return ("fx_len", i, e)
                    return ("fx", i, e)
        for i in range(1, len(rects)):
            if slots[i].trans_in is None:
                continue
            if self._badge_rect(i, slots[i], rects[i]).adjusted(-2, -2, 2, 2).contains(pos):
                return ("trans", i)
            z = self._trans_zone(i, slots[i], rects[i])
            gap_top = self._lane_y(0) + LANE_H                       # its left edge, in the gap between the lanes
            if abs(pos.x() - z.left()) <= 5 and gap_top <= pos.y() <= gap_top + LANE_GAP:
                return ("trans", i)
        for i in reversed(range(len(rects))):
            r = rects[i]
            if r.contains(pos):
                if pos.x() > r.right() - EDGE:
                    return ("edge", i)
                if pos.x() < r.left() + EDGE:
                    return ("edge_l", i)
                return ("track", i)
        return None

    @staticmethod
    def _hit_key(hit):
        if hit is None:
            return None
        if hit[0] in ("fx", "fx_len"):
            return (hit[0], hit[1], hit[2].id)
        return hit

    def _tip(self, hit) -> str:
        if hit is None:
            return ""
        plan = self.state.plan
        if hit[0] in ("fx", "fx_len"):
            e = hit[2]
            beat = 60.0 / (plan.tracks[hit[1]].bpm or plan.master_bpm)
            where = "from the start of the song" if e.anchor == "start" else "before the end of the song"
            return (f"<b>{e.type}</b> · {abs(e.offset) / beat:.2f} beats {where} · lasts {e.duration / beat:.2f} beats<br>"
                    "Drag to move it, drag its right end to make it longer or shorter.<br>"
                    "Arrow keys nudge it (Shift: a whole beat).")
        if hit[0] == "trans":
            tr = plan.transition_after(hit[1] - 1)
            secs = planmod.overlap_seconds(plan, tr)
            return (f"<b>{TRANS_SHORT.get(tr.type, tr.type)}</b> · {tr.overlap_beats} beats ({secs:.1f} s)<br>"
                    "Drag left for a longer blend, right for a shorter one. Click to edit it.")
        return ""

    def _set_blend(self, i: int, beats: int):
        st = self.state

        def fn(p, lib):
            tr = p.transition_after(i - 1)
            new_type = tr.type
            if beats > 0 and tr.type in ("cut", "cut_fx"):
                new_type = "crossfade" if beats < 16 else "eq_swap"
            planmod.set_transition(p, lib, i - 1, new_type, beats)
        st.edit(fn)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            hit = self._hit(pos)
            key = self._hit_key(hit)
            if key != self._hover:
                self._hover = key
                self.update()
                tip = self._tip(hit)
                if tip:
                    QToolTip.showText(ev.globalPosition().toPoint(), tip, self)
                else:
                    QToolTip.hideText()
            if hit and hit[0] in ("edge", "edge_l", "fx_len"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif hit and hit[0] in ("track", "fx", "trans"):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            return
        QToolTip.hideText()
        d = self._drag
        dsec = (pos.x() - d["x0"]) / self.pps
        st = self.state
        plan = st.plan
        self._readout_at = pos
        try:
            if d["kind"] in ("track", "trans") and d["i"] > 0:
                tr = plan.transition_after(d["i"] - 1)
                beat = 60.0 / planmod.tr_tempo(plan, tr)
                beats = max(0, d["beats0"] - round(dsec / beat))
                if beats != tr.overlap_beats:
                    self._set_blend(d["i"], beats)
                tr = st.plan.transition_after(d["i"] - 1)
                self._readout = (f"{TRANS_SHORT.get(tr.type, tr.type)} · {tr.overlap_beats} beats"
                                 f" ({planmod.overlap_seconds(st.plan, tr):.1f} s)")
            elif d["kind"] == "edge":
                t = plan.tracks[d["i"]]
                beat = 60.0 / (t.bpm or plan.master_bpm)
                db = round(dsec / beat)
                an = st.lib[t.song_id]
                new_end = min(an.duration, d["end0"] + db * beat * (t.rate_out or t.rate))
                st.edit(lambda p, lib: planmod.set_track_bounds(p, lib, d["i"], src_end=new_end))
                self._readout = f"ends at {int(new_end // 60)}:{new_end % 60:04.1f} of the song"
            elif d["kind"] == "edge_l":
                i = d["i"]
                t = plan.tracks[i]
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
                self._readout = f"starts at {int(new_start // 60)}:{new_start % 60:04.1f} of the song"
            elif d["kind"] == "fx":
                beat = 60.0 / (plan.tracks[d["i"]].bpm or plan.master_bpm)
                q = beat / 4
                off = d["off0"] + round(dsec / q) * q
                e = d["fx"]
                off = max(0.0, off) if e.anchor == "start" else min(0.5 * beat, off)
                st.edit(lambda p, lib: planmod.update_effect(p, d["i"], e.id, offset=float(off)))
                where = "from the start" if e.anchor == "start" else ("before the end" if off <= 0 else "after the end")
                self._readout = f"{e.type} · {abs(off) / beat:.2f} beats {where}"
            elif d["kind"] == "fx_len":
                beat = 60.0 / (plan.tracks[d["i"]].bpm or plan.master_bpm)
                q = beat / 4
                e = d["fx"]
                dur = min(64 * beat, max(q, d["dur0"] + round(dsec / q) * q))
                st.edit(lambda p, lib: planmod.update_effect(p, d["i"], e.id, duration=float(dur)))
                self._readout = f"{e.type} · lasts {dur / beat:.2f} beats ({dur:.1f} s)"
        except (ValueError, KeyError, IndexError):
            pass
        self.update()

    def keyPressEvent(self, ev):
        """Arrow keys nudge the selected effect by a quarter beat (Shift: a whole beat)."""
        st = self.state
        k = ev.key()
        if k not in (Qt.Key.Key_Left, Qt.Key.Key_Right) or not st.sel_fx or st.sel < 0:
            return super().keyPressEvent(ev)
        plan = st.plan
        try:
            t = plan.tracks[st.sel]
            e = next(x for x in t.effects if x.id == st.sel_fx)
        except (IndexError, StopIteration):
            return super().keyPressEvent(ev)
        beat = 60.0 / (t.bpm or plan.master_bpm)
        step = beat * (1.0 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.25)
        off = e.offset + (step if k == Qt.Key.Key_Right else -step)
        off = max(0.0, off) if e.anchor == "start" else min(0.5 * beat, off)
        st.edit(lambda p, lib: planmod.update_effect(p, st.sel, e.id, offset=float(off)))
        ev.accept()

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
        self._readout, self._readout_at = "", pos
        if hit[0] in ("fx", "fx_len"):
            d.update(fx=hit[2], off0=hit[2].offset, dur0=hit[2].duration)
            st.select(i, hit[2].id)
        elif hit[0] == "trans":
            tr = plan.transition_after(i - 1)
            d.update(beats0=tr.overlap_beats, moved=False)
            st.select(i - 1)
        else:
            tr = plan.transition_after(i - 1) if i > 0 else None
            d.update(beats0=tr.overlap_beats if tr else 0, end0=t.src_end, start0=t.src_start)
            st.select(i)
        st.begin_gesture()
        self._drag = d
        self.setCursor(Qt.CursorShape.SizeHorCursor if hit[0] in ("edge", "edge_l", "fx_len")
                       else Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            d = self._drag
            self._drag = None
            self._readout = ""
            self.state.end_gesture()
            self.unsetCursor()
            if d["kind"] == "trans" and abs(ev.position().x() - d["x0"]) < 4:   # a click, not a drag: edit it
                self.transition_clicked.emit(d["i"] - 1)
            self.update()

    def leaveEvent(self, ev):
        if self._hover is not None and self._drag is None:
            self._hover = None
            self.update()
        super().leaveEvent(ev)

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.pps * (1.15 if ev.angleDelta().y() > 0 else 1 / 1.15))
            ev.accept()
        else:
            ev.ignore()
