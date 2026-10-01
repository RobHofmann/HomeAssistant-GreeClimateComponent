"""Repair flows of the Gree integration."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio
else:
    try:
        import probatio
    except ImportError:
        import voluptuous as probatio

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant

from .migration import ISSUE_LEGACY_ENTRIES, async_remove_legacy_entries


class LegacyEntriesRepairFlow(RepairsFlow):
    """Remove the disabled 4.x config entries after the user confirms."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask for confirmation, then remove the entries."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm", data_schema=probatio.Schema({})
            )

        await async_remove_legacy_entries(self.hass)
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for a fixable issue."""
    if issue_id == ISSUE_LEGACY_ENTRIES:
        return LegacyEntriesRepairFlow()

    raise ValueError(f"Unknown repair issue {issue_id}")
