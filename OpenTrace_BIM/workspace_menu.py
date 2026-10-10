# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared architecture menu groups using the EXISTING creation actions.

The menus provide a discoverable workspace taxonomy without registering tools
again or touching the wall/slab/opening editing palettes.
"""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu


def install_workspace_menu(suite):
    """Attach creation and organization categories to the existing host menu.

    It is safe to call again if a panel is reconstructed; no duplicate menu
    hierarchy or extension actions are created.
    """
    wall=suite.controllers.get("wall")
    root=getattr(wall,"arch_menu",None)
    if not isinstance(root,QMenu):
        return {}
    existing=root.findChild(QMenu,"opentrace_workspace_create",)
    if existing is not None:
        return {"create":existing,"organize":root.findChild(
            QMenu,"opentrace_workspace_organize")}

    # The wall controller initially registers a minimal Parede submenu. Replace
    # ONLY this menu entry; do not delete, recreate or re-register its QActions.
    for action in tuple(root.actions()):
        sub=action.menu()
        if sub is not None and sub.title()=="Parede" and (
                getattr(wall,"simple_wall_action",None) in sub.actions()):
            root.removeAction(action)

    create=QMenu("Criar",root)
    create.setObjectName("opentrace_workspace_create")
    wall_menu=create.addMenu("Paredes")
    for attr in ("simple_wall_action","composite_wall_action","curve_action"):
        action=getattr(wall,attr,None)
        if action is not None:
            wall_menu.addAction(action)

    structural=create.addMenu("Elementos estruturais")
    for key,label in (("slab","Laje"),("column","Pilar"),("beam","Viga")):
        if suite.controllers.get(key) is not None:
            action=QAction(label,structural)
            action.setObjectName("opentrace_create_"+key)
            action.triggered.connect(
                lambda _=False,k=key:suite.user_show_page(k))
            structural.addAction(action)

    openings=create.addMenu("Vãos e esquadrias")
    openings.setObjectName("opentrace_workspace_openings")
    # Reuse the very same opening actions as the top toolbar; no alternative
    # implementation or stale host from a previous selection.
    opening_menu=getattr(wall,"opening_toolbar_menu",None)
    if opening_menu is not None:
        for action in opening_menu.actions():
            openings.addAction(action)
    for kind,title in (("door","Porta"),("window","Janela")):
        section=openings.addMenu(title)
        for anchor,label in (("left","Âncora esquerda"),("center","Âncora central"),
                             ("right","Âncora direita")):
            action=QAction(label,section)
            action.triggered.connect(
                lambda _=False,k=kind,a=anchor:wall.begin_hosted_fill(k,a))
            section.addAction(action)

    organize=QMenu("Organizar e inspecionar",root)
    organize.setObjectName("opentrace_workspace_organize")
    for label,callback in (
        ("Informações do Projeto",lambda:suite.show_page("project")),
        ("BIM / IFC",lambda:suite.show_page("bim")),
        ("Alinhar e distribuir X/Y/Z",suite.open_arrange),
    ):
        action=QAction(label,organize)
        action.triggered.connect(lambda _=False,cb=callback:cb())
        organize.addAction(action)

    # Keep toolbar visibility after a separator and do not change native
    # registration, focus or selection state when constructing the menu.
    toggle=getattr(getattr(wall,"toolbar",None),"toggleViewAction",lambda:None)()
    marker=toggle if toggle in root.actions() else None
    if marker is not None:
        root.insertMenu(marker,create)
        root.insertMenu(marker,organize)
    else:
        root.addMenu(create)
        root.addMenu(organize)
    return {"create":create,"organize":organize}
