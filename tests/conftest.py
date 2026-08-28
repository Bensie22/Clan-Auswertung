"""Macht das Repo-Root importierbar, damit `from app...` in den Tests funktioniert."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
