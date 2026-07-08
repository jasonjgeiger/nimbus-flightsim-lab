<!-- This file is a maintainer guide. It has no Jekyll front matter, so it is not
     built into the published site navigation. -->

# Tutorial site (`/docs`)

This folder is a [Jekyll](https://jekyllrb.com/) site using the
[Just the Docs](https://just-the-docs.com/) theme. It's a tutorial-formatted companion to
the repo README, published to GitHub Pages.

## Publishing (one-time repo setting)

The site deploys via GitHub Actions (`.github/workflows/pages.yml`) on every push to
`main` or `docs/tutorial-site` that touches `docs/**`.

To enable it, a repo admin must set the Pages source once:

**Settings → Pages → Build and deployment → Source → GitHub Actions.**

After that, pushes publish automatically to
`https://jasonjgeiger.github.io/nimbus-flightsim-lab/`.

## Preview locally

```bash
cd docs
bundle install
bundle exec jekyll serve --livereload
# open http://127.0.0.1:4000/nimbus-flightsim-lab/
```

Requires Ruby (3.1+ recommended) and Bundler (`gem install bundler`).

## Structure

Pages are ordered by `nav_order` in each file's front matter:

| nav_order | File | Page |
|-----------|------|------|
| 1 | `index.md` | Home |
| 2 | `understand-nimbus.md` | Understand Nimbus & the SDK |
| 3 | `setup.md` | Set up your system |
| 4 | `tier1-command-dry-run.md` | Tier 1 — Command dry run |
| 5 | `tier2-kinematic-mock.md` | Tier 2 — Kinematic mock |
| 6 | `tier3-flight-simulator.md` | Tier 3 — Flight simulator |
| 7 | `first-agent.md` | Build your first agent |
| 8 | `to-hardware.md` | Transition to Nimbus hardware |
| 9 | `reference.md` | Safety & quick reference |

## Editing conventions

- Keep API specifics (method signatures, argument tables, typed objects) **linked** to the
  [DroneForge Docs](https://droneforge.gitbook.io/droneforge-docs) rather than duplicated —
  that content changes with every SDK release.
- Each tutorial page ends with a **Checkpoint** and a **Next →** link.
- Callouts use Just the Docs classes: `{: .note }`, `{: .warning }`, `{: .highlight }`.
