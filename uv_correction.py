"""UV Correction – pure matplotlib GUI for editing UV coordinates in USD files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.widgets import Button, CheckButtons, Slider, TextBox

from pxr import Gf, Usd, UsdGeom

# ---------------------------------------------------------------------------
# USD helpers
# ---------------------------------------------------------------------------


def list_mesh_prim_paths(stage: Usd.Stage) -> list[str]:
    return [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]


def find_uv_primvar(mesh: UsdGeom.Mesh):
    api = UsdGeom.PrimvarsAPI(mesh)
    for pv in api.GetPrimvars():
        if pv.GetBaseName() in {"st", "uv", "UVMap"}:
            return pv
    for pv in api.GetPrimvars():
        name = pv.GetBaseName().lower()
        if "st" in name or "uv" in name:
            return pv
    return None


def get_uv_values(stage: Usd.Stage, mesh_path: str):
    prim = stage.GetPrimAtPath(mesh_path)
    if not prim or not prim.IsA(UsdGeom.Mesh):
        return None, None
    mesh = UsdGeom.Mesh(prim)
    pv = find_uv_primvar(mesh)
    if pv is None:
        return None, None
    return pv, pv.Get()


def transform_uvs(values, scale_u: float, scale_v: float, offset_u: float, offset_v: float):
    return [Gf.Vec2f(uv[0] * scale_u + offset_u, uv[1] * scale_v + offset_v) for uv in values]


def is_identity_transform(scale_u: float, scale_v: float, offset_u: float, offset_v: float) -> bool:
    return (
        abs(scale_u - 1.0) < 1e-9
        and abs(scale_v - 1.0) < 1e-9
        and abs(offset_u) < 1e-9
        and abs(offset_v) < 1e-9
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class UVCorrectionApp:
    def __init__(self, usd_path: str, texture_path: str | None = None) -> None:
        self.stage = Usd.Stage.Open(usd_path)
        if self.stage is None:
            print(f"Error: Could not open USD file: {usd_path}", file=sys.stderr)
            sys.exit(1)

        self.usd_path = Path(usd_path)
        self.mesh_paths = list_mesh_prim_paths(self.stage)
        if not self.mesh_paths:
            print("No meshes found in the USD file.", file=sys.stderr)
            sys.exit(1)

        # Store original UVs and modified UVs
        self.original_uvs: dict[str, list] = {}
        self.modified_uvs: dict[str, list] = {}
        for mp in self.mesh_paths:
            _pv, vals = get_uv_values(self.stage, mp)
            if vals is not None:
                self.original_uvs[mp] = list(vals)

        self.texture_image = None
        self.flip_texture_x = False
        self.flip_texture_y = False
        if texture_path:
            try:
                self.texture_image = plt.imread(texture_path)
            except Exception as e:
                print(f"Warning: Could not load texture: {e}", file=sys.stderr)

        # Selected meshes (all selected by default)
        self.selected: dict[str, bool] = {mp: True for mp in self.mesh_paths}
        self.live_preview = True
        self.view_xlim: tuple[float, float] | None = None
        self.view_ylim: tuple[float, float] | None = None
        self.is_panning = False
        self.pan_start: tuple[float, float, tuple[float, float], tuple[float, float]] | None = None

        # Keep checkbox labels short to avoid text overflow.
        self.mesh_label_to_path: dict[str, str] = {}
        self.mesh_paths_by_label: list[str] = []
        self.mesh_labels: list[str] = []
        self._build_mesh_labels()

        self._build_ui()

    def _build_mesh_labels(self) -> None:
        self.mesh_label_to_path.clear()
        self.mesh_paths_by_label.clear()
        self.mesh_labels.clear()

        for i, mp in enumerate(self.mesh_paths, start=1):
            base = mp.split("/")[-1]
            if len(base) > 24:
                base = base[:21] + "..."
            label = f"{i:02d} {base}"
            self.mesh_label_to_path[label] = mp
            self.mesh_paths_by_label.append(mp)
            self.mesh_labels.append(label)

    # ---- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        self.fig = plt.figure("UV Correction Tool", figsize=(14, 9))

        # Main UV plot area
        self.ax = self.fig.add_axes([0.30, 0.15, 0.65, 0.80])

        # Mesh checkboxes (left side)
        actives = [self.selected[mp] for mp in self.mesh_paths]

        ax_check = self.fig.add_axes([0.01, 0.35, 0.22, 0.60])
        ax_check.set_title("Meshes", fontsize=10, fontweight="bold")
        self.check = CheckButtons(ax_check, self.mesh_labels, actives)
        for txt in self.check.labels:
            txt.set_fontsize(8)
        self.check.on_clicked(self._on_check)

        # Sliders (bottom)
        ax_su = self.fig.add_axes([0.35, 0.06, 0.25, 0.03])
        ax_sv = self.fig.add_axes([0.35, 0.02, 0.25, 0.03])
        ax_ou = self.fig.add_axes([0.70, 0.06, 0.25, 0.03])
        ax_ov = self.fig.add_axes([0.70, 0.02, 0.25, 0.03])

        self.sl_su = Slider(ax_su, "Scale U", 0.01, 100.0, valinit=1.0)
        self.sl_sv = Slider(ax_sv, "Scale V", 0.01, 100.0, valinit=1.0)
        self.sl_ou = Slider(ax_ou, "Offset U", -2.0, 2.0, valinit=0.0)
        self.sl_ov = Slider(ax_ov, "Offset V", -2.0, 2.0, valinit=0.0)

        # Exact numeric input fields.
        ax_tsu = self.fig.add_axes([0.61, 0.06, 0.07, 0.03])
        ax_tsv = self.fig.add_axes([0.61, 0.02, 0.07, 0.03])
        ax_tou = self.fig.add_axes([0.96, 0.06, 0.03, 0.03])
        ax_tov = self.fig.add_axes([0.96, 0.02, 0.03, 0.03])

        self.tb_su = TextBox(ax_tsu, "", initial="1.0")
        self.tb_sv = TextBox(ax_tsv, "", initial="1.0")
        self.tb_ou = TextBox(ax_tou, "", initial="0.0")
        self.tb_ov = TextBox(ax_tov, "", initial="0.0")

        self.tb_su.on_submit(lambda txt: self._textbox_to_slider(txt, self.sl_su, 0.01, 100.0))
        self.tb_sv.on_submit(lambda txt: self._textbox_to_slider(txt, self.sl_sv, 0.01, 100.0))
        self.tb_ou.on_submit(lambda txt: self._textbox_to_slider(txt, self.sl_ou, -2.0, 2.0))
        self.tb_ov.on_submit(lambda txt: self._textbox_to_slider(txt, self.sl_ov, -2.0, 2.0))

        # Reactive view: redraw while slider values change.
        self.sl_su.on_changed(self._on_slider_change)
        self.sl_sv.on_changed(self._on_slider_change)
        self.sl_ou.on_changed(self._on_slider_change)
        self.sl_ov.on_changed(self._on_slider_change)

        # Buttons (left bottom)
        ax_apply = self.fig.add_axes([0.01, 0.24, 0.22, 0.05])
        ax_apply_all = self.fig.add_axes([0.01, 0.18, 0.22, 0.05])
        ax_reset = self.fig.add_axes([0.01, 0.12, 0.22, 0.05])
        ax_export = self.fig.add_axes([0.01, 0.04, 0.22, 0.06])

        # View controls (top right)
        ax_zoom_in = self.fig.add_axes([0.73, 0.95, 0.07, 0.035])
        ax_zoom_out = self.fig.add_axes([0.81, 0.95, 0.07, 0.035])
        ax_view_reset = self.fig.add_axes([0.89, 0.95, 0.08, 0.035])

        self.btn_apply = Button(ax_apply, "Apply to Selection")
        self.btn_apply_all = Button(ax_apply_all, "Apply to ALL")
        self.btn_reset = Button(ax_reset, "Reset")
        self.btn_export = Button(ax_export, "Export")
        self.btn_zoom_in = Button(ax_zoom_in, "Zoom +")
        self.btn_zoom_out = Button(ax_zoom_out, "Zoom -")
        self.btn_view_reset = Button(ax_view_reset, "View Reset")

        self.btn_apply.on_clicked(self._apply_selected)
        self.btn_apply_all.on_clicked(self._apply_all)
        self.btn_reset.on_clicked(self._reset)
        self.btn_export.on_clicked(self._export)
        self.btn_zoom_in.on_clicked(self._zoom_in)
        self.btn_zoom_out.on_clicked(self._zoom_out)
        self.btn_view_reset.on_clicked(self._reset_view)

        # Texture display options.
        ax_tex = self.fig.add_axes([0.01, 0.30, 0.22, 0.04])
        self.check_tex = CheckButtons(
            ax_tex,
            ["Texture X Flip", "Texture Y Flip"],
            [self.flip_texture_x, self.flip_texture_y],
        )
        for txt in self.check_tex.labels:
            txt.set_fontsize(8)
        self.check_tex.on_clicked(self._on_texture_option)

        # Mouse navigation: right-click and drag to pan the UV view.
        self.fig.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.fig.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)

        self._sync_textboxes_from_sliders()
        self._refresh_plot()

    # ---- Callbacks --------------------------------------------------------

    def _on_check(self, label: str) -> None:
        mp = self.mesh_label_to_path.get(label)
        if mp is None:
            return
        self.selected[mp] = not self.selected[mp]
        self._refresh_plot()

    def _on_slider_change(self, _val: float) -> None:
        self._sync_textboxes_from_sliders()
        if self.live_preview:
            self._refresh_plot()

    def _on_texture_option(self, label: str) -> None:
        if label == "Texture X Flip":
            self.flip_texture_x = not self.flip_texture_x
        elif label == "Texture Y Flip":
            self.flip_texture_y = not self.flip_texture_y
        self._refresh_plot()

    def _sync_textboxes_from_sliders(self) -> None:
        self.tb_su.set_val(f"{self.sl_su.val:.4f}")
        self.tb_sv.set_val(f"{self.sl_sv.val:.4f}")
        self.tb_ou.set_val(f"{self.sl_ou.val:.4f}")
        self.tb_ov.set_val(f"{self.sl_ov.val:.4f}")

    def _zoom(self, scale: float) -> None:
        if self.view_xlim is None or self.view_ylim is None:
            x0, x1 = self.ax.get_xlim()
            y0, y1 = self.ax.get_ylim()
        else:
            x0, x1 = self.view_xlim
            y0, y1 = self.view_ylim

        cx = (x0 + x1) * 0.5
        cy = (y0 + y1) * 0.5
        hx = (x1 - x0) * 0.5 * scale
        hy = (y1 - y0) * 0.5 * scale

        self.view_xlim = (cx - hx, cx + hx)
        self.view_ylim = (cy - hy, cy + hy)
        self._refresh_plot()

    def _zoom_in(self, _event=None) -> None:
        self._zoom(0.8)

    def _zoom_out(self, _event=None) -> None:
        self._zoom(1.25)

    def _reset_view(self, _event=None) -> None:
        self.view_xlim = None
        self.view_ylim = None
        self._refresh_plot()

    def _on_mouse_press(self, event) -> None:
        if event.inaxes != self.ax or event.button != 3:
            return
        if event.xdata is None or event.ydata is None:
            return

        if self.view_xlim is None or self.view_ylim is None:
            self.view_xlim = self.ax.get_xlim()
            self.view_ylim = self.ax.get_ylim()

        self.is_panning = True
        self.pan_start = (event.xdata, event.ydata, self.view_xlim, self.view_ylim)

    def _on_mouse_release(self, event) -> None:
        if event.button == 3:
            self.is_panning = False
            self.pan_start = None

    def _on_mouse_move(self, event) -> None:
        if not self.is_panning or self.pan_start is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        start_x, start_y, start_xlim, start_ylim = self.pan_start
        dx = event.xdata - start_x
        dy = event.ydata - start_y

        self.view_xlim = (start_xlim[0] - dx, start_xlim[1] - dx)
        self.view_ylim = (start_ylim[0] - dy, start_ylim[1] - dy)
        self._refresh_plot()

    def _textbox_to_slider(self, text: str, slider: Slider, min_v: float, max_v: float) -> None:
        try:
            value = float(text.strip())
        except ValueError:
            self._sync_textboxes_from_sliders()
            return

        value = max(min_v, min(max_v, value))
        slider.set_val(value)

    def _get_selected_paths(self) -> list[str]:
        return [mp for mp in self.mesh_paths if self.selected.get(mp)]

    def _apply_transform(self, paths: list[str]) -> None:
        su, sv = self.sl_su.val, self.sl_sv.val
        ou, ov = self.sl_ou.val, self.sl_ov.val
        for mp in paths:
            base = self.modified_uvs.get(mp, self.original_uvs.get(mp))
            if base is None:
                continue
            self.modified_uvs[mp] = transform_uvs(base, su, sv, ou, ov)
        # After committing, reset controls to avoid a second preview transform on top.
        self.sl_su.set_val(1.0)
        self.sl_sv.set_val(1.0)
        self.sl_ou.set_val(0.0)
        self.sl_ov.set_val(0.0)
        self._sync_textboxes_from_sliders()
        self._refresh_plot()

    def _apply_selected(self, _event=None) -> None:
        self._apply_transform(self._get_selected_paths())

    def _apply_all(self, _event=None) -> None:
        self._apply_transform(self.mesh_paths)

    def _reset(self, _event=None) -> None:
        for mp in self._get_selected_paths():
            self.modified_uvs.pop(mp, None)
        self.sl_su.set_val(1.0)
        self.sl_sv.set_val(1.0)
        self.sl_ou.set_val(0.0)
        self.sl_ov.set_val(0.0)
        self._sync_textboxes_from_sliders()
        self._refresh_plot()

    def _export(self, _event=None) -> None:
        out = self.usd_path.with_stem(self.usd_path.stem + "_corrected").with_suffix(".usda")

        changed = 0
        for mesh_path in self.mesh_paths:
            pv, _ = get_uv_values(self.stage, mesh_path)
            if pv is None:
                continue
            vals = self._values_for_display(mesh_path)
            if vals is None:
                continue
            if pv.Set(vals):
                changed += 1

        self.stage.Export(str(out))
        print(f"Exported: {out} ({changed} mesh primvars written)")
        self.ax.set_title(f"Exported: {out.name}", fontsize=10, color="green")
        self.fig.canvas.draw_idle()

    def _values_for_display(self, mesh_path: str):
        base = self.modified_uvs.get(mesh_path, self.original_uvs.get(mesh_path))
        if base is None:
            return None

        if not self.live_preview or mesh_path not in self._get_selected_paths():
            return base

        su, sv = self.sl_su.val, self.sl_sv.val
        ou, ov = self.sl_ou.val, self.sl_ov.val
        if is_identity_transform(su, sv, ou, ov):
            return base

        return transform_uvs(base, su, sv, ou, ov)

    # ---- Plotting ---------------------------------------------------------

    def _refresh_plot(self) -> None:
        self.ax.clear()

        if self.texture_image is not None:
            tex = self.texture_image
            if self.flip_texture_x:
                tex = tex[:, ::-1]
            if self.flip_texture_y:
                tex = tex[::-1, :]
            self.ax.imshow(
                tex, extent=[0, 1, 0, 1], origin="lower", aspect="auto",
            )

        selected_paths = set(self._get_selected_paths())

        for mp in self.mesh_paths:
            vals = self._values_for_display(mp)
            if vals is None:
                continue
            us = [float(v[0]) for v in vals]
            vs = [float(v[1]) for v in vals]

            is_sel = mp in selected_paths
            color = "red" if is_sel else "gray"
            alpha = 0.9 if is_sel else 0.2
            label = mp.split("/")[-1] if is_sel else None
            self.ax.scatter(us, vs, s=10, c=color, alpha=alpha, label=label)

        self.ax.set_xlabel("U")
        self.ax.set_ylabel("V")
        self.ax.set_title("UV Coordinates")
        self.ax.grid(True, alpha=0.3)
        if self.view_xlim is not None and self.view_ylim is not None:
            self.ax.set_xlim(*self.view_xlim)
            self.ax.set_ylim(*self.view_ylim)
        else:
            # Default UV domain when view is reset.
            self.ax.set_xlim(0.0, 1.0)
            self.ax.set_ylim(0.0, 1.0)
        if selected_paths:
            self.ax.legend(fontsize=8, loc="upper right")
        self.fig.canvas.draw_idle()

    def run(self) -> None:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="UV Correction Tool - Correct UV coordinates in USD files",
    )
    parser.add_argument("usd_file", help="Path to the USD file")
    parser.add_argument(
        "--texture",
        "-t",
        "-texture",
        dest="texture",
        help="Path to the texture image file",
    )
    args = parser.parse_args()

    app = UVCorrectionApp(args.usd_file, args.texture)
    app.run()


if __name__ == "__main__":
    main()
