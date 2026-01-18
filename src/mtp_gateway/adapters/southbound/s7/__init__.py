"""Siemens S7 PLC connector module.

Provides communication with Siemens S7-300/400/1200/1500 PLCs
using the python-snap7 library.
"""

from mtp_gateway.adapters.southbound.s7.driver import S7Connector

__all__ = ["S7Connector"]
