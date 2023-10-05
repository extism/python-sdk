# Extism Python Host SDK

See [https://extism.org/docs/integrate-into-your-codebase/python-host-sdk/](https://extism.org/docs/integrate-into-your-codebase/python-host-sdk/).


## Development

### Release workflow

1. Create a semver-formatted git tag (`git tag v1.0.0`).
2. Push that tag to the repository (`git push origin v1.0.0`.)
3. Wait for [the Build workflow to run](https://github.com/extism/python-sdk/actions/workflows/build.yaml).
4. Once the build workflow finishes, go to the [releases](https://github.com/extism/python-sdk/releases) page. You should
   see a draft release.
5. Edit the draft release. Publish the release.
6. Wait for [the Release workflow to run](https://github.com/extism/python-sdk/actions/workflows/release.yaml).
7. Once the release workflow completes, you should be able to `pip install extism==${YOUR_TAG}` from PyPI.

