"""Detection accuracy evaluation against labelled ground truth.

Separate from `overwatch.detection` on purpose: the detector must never import anything
from here, so scoring code can never influence what is detected.
"""
