# Preserve app data across routine deployments

Each app has a separate database whose data survives ordinary restarts and redeployments, with explicit reset and deletion operations. The pilot provides no backup or recovery guarantee: disposable means users can afford to lose the data, while erasing it during routine publishing would undermine the repeated-use experiment.
