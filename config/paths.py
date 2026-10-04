"""Zusätzliche erlaubte Arbeitsordner; Projektordner werden vom Nutzer gewählt."""
ALLOWED_ROOTS = []
 
from pathlib import Path
 
# Nur bei ausdrücklich gewählter automatischer Workspace-Erstellung.
WORKSPACE_BASE = Path.home() / 'CLS' / 'workspaces'