# Files to put in place by hand

The remote file tool may not write Git hook or CI configuration, so these three files are
parked here. Move them once, then delete this `setup` folder:

| From | To |
|---|---|
| `setup/pre-commit-config.yaml` | `.pre-commit-config.yaml` |
| `setup/github-workflows/pr-ci.yml` | `.github/workflows/pr-ci.yml` |
| `setup/github-workflows/deploy-ecs.yml` | `.github/workflows/deploy-ecs.yml` |

PowerShell, from the project folder:

```powershell
Move-Item setup\pre-commit-config.yaml .pre-commit-config.yaml
New-Item -ItemType Directory -Force .github\workflows | Out-Null
Move-Item setup\github-workflows\*.yml .github\workflows\
Remove-Item -Recurse setup
```
