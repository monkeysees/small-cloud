# Separate network restrictions from database authorization

Tool runtimes may reach the public internet but must not reach private networks, cloud metadata endpoints, or platform management services, except for the specifically permitted database connection. Metadata blocking remains mandatory rather than being replaced with a low-permission cloud identity; hosting selection must demonstrate this boundary.

Each tool has a separate logical database and restricted user, potentially on a shared database server. Database authorization must prevent access to other tools' databases; separate network endpoints are not required. This preserves the data boundary without requiring a database server per tool within the pilot budget.
