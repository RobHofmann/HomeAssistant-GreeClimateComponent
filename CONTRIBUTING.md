# Contributing

This integration follows the development guidelines for Home Assistant integrations, while keeping the repository compatible with HACS.

## Development Environment

Home Assistant provides [several guidelines](https://developers.home-assistant.io/docs/development_environment) regarding the setup of the development environment. Because we are not contributing to the official integrations, there is no need to fork the official [Home Assistant Core](https://github.com/home-assistant/core) repository. 

This repository includes a DevContainer to improve the development experience. To use it ensure your are using a machine that support DevContainers


1. Fork [this](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent) repository and clone your fork (for example at `gree-ha-climate`)
2. Create a branch for your changes in the cloned repo `git checkout -b my-branch-name`
3. Open `gree-ha-climate` with VSCode, locally or with the Remote SSH extension
4. Use the command **"Dev Containers: Reopen in Container"**
    * It takes a few minutes to create the container for the first time 
5.  Once inside the container you should be able to see the repo files and have a working development environment
6.  Make your changes
    *  Use the provided Tasks to Run HomeAssistant and debug the integration as required
7.  Push to your fork, rebase with the latest upstream version and submit a pull request

## Testing

Use the **Run Home Assistant** Task to start Home Assistant.

You should also be able to set and hit breakpoints in your code.

If you change your code, you have to restart Home Assistant (rerun the Task)

## Styling

Please adhere to the recomended coding style: https://developers.home-assistant.io/docs/development_guidelines