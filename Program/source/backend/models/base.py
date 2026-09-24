"""M2 models base class. Every table module imports this Base."""
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
