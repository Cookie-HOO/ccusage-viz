# README screenshots

This directory is the shared image location for the English and Simplified
Chinese READMEs. Both landing pages use these exact names and paths.

## Dashboard presets

| File | Used for | Command represented |
| --- | --- | --- |
| `dashboard-wide-clock.png` | Default Dashboard: wide layout with an analog-clock Pane | `ccuv dashboard` / `ccuv dashboard wide-clock` |
| `dashboard-narrow-clock.png` | Narrow Dashboard with a digital-clock Pane | `ccuv dashboard narrow-clock` |
| `dashboard-wide.png` | Balanced 2×2 Dashboard overview | `ccuv dashboard wide` |
| `dashboard-narrow.png` | Compact, vertically focused Dashboard | `ccuv dashboard narrow` |
| `dashboard-all.png` | Broad Dashboard gallery | `ccuv dashboard all` |
| `dashboard-spotlight-wide.png` | Dashboard with Timeline in the leading full-width row | `ccuv dashboard spotlight-wide` |
| `dashboard-spotlight-wide2.png` | Dashboard with Timeline and Stack in consecutive full-width rows | `ccuv dashboard spotlight-wide2` |

## Standalone views

| File | Used for | Command represented |
| --- | --- | --- |
| `standalone-calendar.png` | Calendar heatmap | `ccuv calendar` |
| `standalone-ranking.png` | Project ranking | `ccuv ranking --by project` |
| `standalone-stack-composition.png` | Token-composition Stack chart | `ccuv stack` |
| `standalone-stack-cache-split.png` | Stack chart with cache reads and creation separated | `ccuv stack --cache split` |
| `standalone-timeline-14d.png` | 14-day Timeline trend | `ccuv timeline` |
| `standalone-timeline-13mo.png` | 13-month Timeline trend | `ccuv timeline --period 13mo` |
| `standalone-animation-gallery.gif` | Animation-style gallery | `ccuv animate --gallery` |
| `standalone-monitor-throughput.png` | Observed Monitor throughput window | `ccuv monitor` |
| `standalone-monitor-cumulative-bars.png` | Monitor local-day cumulative token distribution | `ccuv monitor --style cumulative-bars` |
| `standalone-monitor-ranking.png` | Monitor grouped ranking | `ccuv monitor --by project` |
| `standalone-monitor-list.png` | Monitor process/list detail | `ccuv monitor` |
| `standalone-monitor-animation.gif` | Optional animation attached beneath Monitor ranking or list data | Monitor `m`, then `s` |

Before committing a replacement, inspect it at native size. It must be legible
and settled, with no clipping, shell prompt, dependency-install prompt, error,
loading state, local path, or private usage data. Keep static images as PNG and
intentional motion captures as GIF in this directory; preserve the filename
contract above.
