"""Message channels for Memoranda.

`base` holds the seam and the binding table. `telegram` is the one adapter
implemented. A second channel is a new file in here, and nothing outside this
package should have to change.
"""

from .base import BindingStore, Channel  # noqa: F401
