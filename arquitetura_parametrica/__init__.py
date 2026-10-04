# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric architecture tools for IngeTrazo 0.5.7 — profiled walls and hosted openings.

Development draft: implementation only; runtime validation is pending.
Keep this package's directory name stable: it identifies the extension.
"""

__version__ = "0.10.2-dev-profile-library-ui"


def setup(app):
    # Import implementation from submodules: the host must not discover the
    # spatial tool as a one-shot menu tool and instantiate it without its UI.
    from .host import require_reference_host
    from .ui import WallController

    require_reference_host(app)
    controller = WallController(app)
    # Keep secondary tools isolated during development: a fault in one must not
    # turn the whole architecture package into a load-error plugin.
    import logging
    log = logging.getLogger("ingetrazo.plugins.arquitetura_parametrica")
    startup_errors = []
    slab_controller = None
    column_controller = None
    beam_controller = None
    profile_controller = None
    try:
        from .slab_ui import SlabController
        slab_controller = SlabController(app, controller)
    except Exception as exc:  # development isolation; full traceback in log
        log.exception("parametric slab setup failed")
        startup_errors.append(f"Laje: {type(exc).__name__}: {exc}")
    try:
        from .column_ui import ColumnController
        column_controller = ColumnController(app, controller)
    except Exception as exc:  # development isolation; full traceback in log
        log.exception("parametric column setup failed")
        startup_errors.append(f"Pilar: {type(exc).__name__}: {exc}")
    try:
        from .beam_ui import BeamController
        beam_controller = BeamController(app, controller)
    except Exception as exc:
        log.exception("parametric beam setup failed")
        startup_errors.append(f"Viga: {type(exc).__name__}: {exc}")

    try:
        from .profile_editor import ComplexProfileController
        profile_controller = ComplexProfileController(app, controller)
    except Exception as exc:
        log.exception("complex profile editor setup failed")
        startup_errors.append(f"Perfil Complexo: {type(exc).__name__}: {exc}")

    # QObject parenting owns the widgets; these references also retain Python
    # callbacks and tools for the application window.
    app.window._arquitetura_parametrica_controller = controller
    app.window._arquitetura_parametrica_slab_controller = slab_controller
    app.window._arquitetura_parametrica_column_controller = column_controller
    app.window._arquitetura_parametrica_beam_controller = beam_controller
    app.window._arquitetura_parametrica_profile_controller = profile_controller
    try:
        from .context_guard import ParametricContextGuard
        context_guard = ParametricContextGuard(app, [controller, slab_controller, column_controller, beam_controller])
    except Exception as exc:
        log.exception("parametric context guard setup failed")
        context_guard = None
        startup_errors.append(f"Contexto: {type(exc).__name__}: {exc}")
    app.window._arquitetura_parametrica_context_guard = context_guard
    app.window._arquitetura_parametrica_startup_errors = startup_errors
    if startup_errors:
        controller.message(" | ".join(startup_errors), error=True)