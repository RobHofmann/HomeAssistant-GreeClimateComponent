# Contributing

This integration follows the development guidelines for Home Assistant integrations, while keeping the repository compatible with HACS.

## Development Environment

Home Assistant provides [several guidelines](https://developers.home-assistant.io/docs/development_environment) regarding the setup of the development environment. Because we are not contributing to the official integrations, there is no need to fork the official [Home Assistant Core](https://github.com/home-assistant/core) repository. However, it is useful to use it as it provides a preconfigured VSCode development environment with the necessary tools.

Here's a general guide to get it working with this integration repository:

1. Create a folder for the development (for example `development/`)
2. Clone [home-assistant/core ](https://github.com/home-assistant/core) inside of it (`development/core`)
3. Follow the [guidelines](https://developers.home-assistant.io/docs/development_environment) on getting the devcontainer working
4. Fork [this](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent) repository and clone your fork inside of the same folder (`development/YourForkName`)
5. Create a branch for your changes in the cloned repo `git checkout -b my-branch-name`
6. Create a mount point for this integration in the devcontainer
    1. Open `development/core/devcontainer/devcontainer.json`
    2. Add the mounting:
	```json
		"mounts": [
			"source=${localWorkspaceFolder}/../YourForkName/custom_components/gree_custom,target=/workspaces/core/config/custom_components/gree_custom,type=bind"
		],
	```
7. Open `development/core` with VSCode
8. Use the command **"Dev Containers: Reopen in Container"**
9. Once inside the container make sure the folder `config/custom_components/gree_custom` exists
10. You should be now be able to edit the integration files from inside the devcontainer
11. Make your changes
12. Push to your fork, rebase with the latest upstream version and submit a pull request

## Testing

Use the **Run Home Assistant Core** Task to start Home Assistant.

You should also be able to set and hit breakpoints in your code.

If you change your code, you have to restart Home Assistant (rerun the Task)

## Styling

Please adhere to the recomended coding style: https://developers.home-assistant.io/docs/development_guidelines