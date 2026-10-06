# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric architecture tools for IngeTrazo 0.5.7+ — profiled walls and hosted openings.

Development draft: implementation only; runtime validation is pending.
Keep this package's directory name stable: it identifies the extension.
"""

__version__ = "0.11.1"


def setup(app):
    # Import implementation from submodules: the host must not discover the
    # spatial tool as a one-shot menu tool and instantiate it without its UI.
    from .host import require_reference_host
    from .ui import WallController

    require_reference_host(app)

    # Register exactly ONE extension dock before the host restores its saved
    # window state.  Previous 0.11 builds created five temporary docks and,
    # after the window was already visible, removed/reparented them into the
    # unified panel.  On Windows that late dock surgery could perturb the
    # restored/maximized geometry and leave the menu bar in an odd activation
    # state.  Every architecture controller now points at this stable dock
    # from the beginning; its contents are installed after the controllers
    # exist, but its identity/layout never changes during startup.
    from PySide6.QtWidgets import QWidget
    _suite_bootstrap = QWidget()
    _suite_bootstrap.setMinimumSize(0, 0)
    _master_dock = app.add_panel(
        "Parametric Architecture", _suite_bootstrap,
        name="parametric_architecture",
    )
    _master_dock.hide()
    app.window._arquitetura_parametrica_master_dock = _master_dock

    try:
        from .layer_intersections import configure as configure_layer_intersections
        configure_layer_intersections(app)
    except Exception:
        pass
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

    preset_catalog = None
    try:
        from .preset_catalog import PresetCatalogController
        preset_catalog = PresetCatalogController({
            "wall": controller,
            "slab": slab_controller,
            "column": column_controller,
            "beam": beam_controller,
        })
    except Exception as exc:
        log.exception("parametric preset catalogue setup failed")
        startup_errors.append(f"Presets: {type(exc).__name__}: {exc}")
    app.window._arquitetura_parametrica_preset_catalog = preset_catalog

    resource_library = None
    try:
        from .resource_presets import install_resource_library
        resource_library = install_resource_library(app, controller)
    except (ImportError, ModuleNotFoundError):
        # Extension API 4 is optional. Built-in/personal presets continue to
        # work through preset_catalog.py on current stable IngeTrazo builds.
        resource_library = None
    except RuntimeError as exc:
        if "Extension API 4" in str(exc):
            resource_library = None
        else:
            log.exception("parametric resource library setup failed")
            startup_errors.append(f"Biblioteca: {type(exc).__name__}: {exc}")
    except Exception as exc:
        log.exception("parametric resource library setup failed")
        startup_errors.append(f"Biblioteca: {type(exc).__name__}: {exc}")
    app.window._arquitetura_parametrica_resource_library = resource_library
    try:
        from .context_guard import ParametricContextGuard
        context_guard = ParametricContextGuard(app, [controller, slab_controller, column_controller, beam_controller])
    except Exception as exc:
        log.exception("parametric context guard setup failed")
        context_guard = None
        startup_errors.append(f"Contexto: {type(exc).__name__}: {exc}")
    app.window._arquitetura_parametrica_context_guard = context_guard

    # The master dock already exists and is known to the host before
    # restoreState().  Populate it now; no post-show QTimer, addDockWidget,
    # removeDockWidget or focus-changing raise is needed.
    app.window._arquitetura_parametrica_suite_panel = None
    try:
        from .suite_panel import ArchitectureSuitePanel
        suite_panel = ArchitectureSuitePanel(
            app, controller, slab_controller, column_controller,
            beam_controller, profile_controller, master_dock=_master_dock,
        )
        app.window._arquitetura_parametrica_suite_panel = suite_panel
    except Exception as exc:
        log.exception("parametric unified sidebar setup failed")
        startup_errors.append(f"Painel: {type(exc).__name__}: {exc}")
        controller.message(f"Painel: {type(exc).__name__}: {exc}", error=True)

    app.window._arquitetura_parametrica_startup_errors = startup_errors
    if startup_errors:
        controller.message(" | ".join(startup_errors), error=True)
