# Collaboration Rules

## Branch Naming
- Branch names must use the format `type/work-description`.
- `type` must be lowercase.
- `work-description` should be written in English and connected with hyphens.
- Example: `feat/implement-google-login`

## Branch Safety
- Never implement features or additional work directly on the `main` branch.
- Before starting any code or document change, create and switch to a working branch that follows the naming rule.
- Treat `main` as a protected integration branch for reviewed changes only.

## Work Types
| Type | Meaning |
| --- | --- |
| `feat` | Add a new feature |
| `fix` | Fix a bug |
| `docs` | Update documentation |
| `style` | Formatting-only change with no code behavior change |
| `refactor` | Refactor existing code |
| `test` | Add or improve tests |
| `chore` | Dependency updates or small maintenance work |
| `db` | Database schema changes |

## Team Notes
- Keep branch names consistent across the team.
- Choose the type based on the main purpose of the change.
- If multiple changes are mixed, name the branch after the highest-impact task.
- Write commit messages in Korean.
