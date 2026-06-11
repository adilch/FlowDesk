"""FlowDesk - a desktop GUI for OpenFOAM CFD simulations.

Layer map (imports allowed only downward, PRD §7.1):

    flowdesk.ui        PyQt6 widgets, QSS theme, viewer widgets
    flowdesk.app       application services (project mgr, validation, staleness, undo)
    flowdesk.model     typed case model - single source of truth
    flowdesk.foam      OpenFOAM adapter (model <-> dictionaries via foamlib)
    flowdesk.exec      execution engine (process mgr, pipelines, parsers)
    flowdesk.platform  env discovery, WSL2 bridge, path translation
"""

__version__ = "0.1.0"
