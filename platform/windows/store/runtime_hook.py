"""Initialize the MSIX writable profile before application modules load."""
from core.distribution import bootstrap

bootstrap()
