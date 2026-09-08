# Separate network restrictions from database authorization

App runtimes may reach the public internet but must not reach private networks, cloud metadata endpoints, or platform management services, except for the specifically permitted database connection. Metadata blocking remains mandatory rather than being replaced with a low-permission cloud identity; hosting selection must demonstrate this boundary.

Each app has a separate logical database and restricted user, potentially on a shared database server. Database authorization must prevent access to other apps' databases; separate network endpoints are not required. This preserves the data boundary without requiring a database server per app within the pilot budget.
