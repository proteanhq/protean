from protean import Domain, UnitOfWork, current_domain
from protean.exceptions import ExpectedVersionError
from protean.fields import Auto, Boolean, Identifier, String

domain = Domain(name="OptimisticConcurrencyPreferences")


# --8<-- [start:aggregate]
@domain.aggregate
class UserPreferences:
    user_id: Auto(identifier=True)
    theme: String(default="light")
    language: String(default="en")
    notifications_enabled: Boolean(default=True)
    sidebar_collapsed: Boolean(default=False)

    def update_theme(self, theme: str) -> None:
        self.theme = theme
        self.raise_(
            ThemeUpdated(
                user_id=self.user_id,
                theme=theme,
            )
        )

    def toggle_notifications(self, enabled: bool) -> None:
        self.notifications_enabled = enabled
        self.raise_(
            NotificationsToggled(
                user_id=self.user_id,
                enabled=enabled,
            )
        )


# --8<-- [end:aggregate]


@domain.event(part_of=UserPreferences)
class ThemeUpdated:
    user_id: Identifier(required=True)
    theme: String(required=True)


@domain.event(part_of=UserPreferences)
class NotificationsToggled:
    user_id: Identifier(required=True)
    enabled: Boolean(required=True)


# --8<-- [start:service]
MAX_RETRIES = 3


@domain.application_service(part_of=UserPreferences)
class PreferencesService:
    def update_theme(self, user_id: str, theme: str) -> UserPreferences:
        for attempt in range(MAX_RETRIES):
            try:
                # Each attempt is its own transaction. The version check
                # runs when the unit of work commits, so the except clause
                # must sit outside the `with` block.
                with UnitOfWork():
                    repo = current_domain.repository_for(UserPreferences)
                    prefs = repo.get(user_id)
                    prefs.update_theme(theme)
                    repo.add(prefs)
                return prefs
            except ExpectedVersionError:
                if attempt == MAX_RETRIES - 1:
                    raise


# --8<-- [end:service]
