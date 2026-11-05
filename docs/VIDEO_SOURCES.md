# Video discovery notes

Reviewed November 3, 2026 (America/New_York).

These references describe source provenance and access boundaries. They do not
supply current-season video rights or establish model accuracy. Source downloads,
private verification results, and footage stay outside Git.

## Short archival samples with listed reuse licenses

| Source | Subject / duration | License and attribution | Intended use |
| --- | --- | --- | --- |
| [Kobe Bryant warmup](https://commons.wikimedia.org/wiki/File:Kobe_Bryant.ogv) | Kobe Bryant free throw during Lakers/Warriors warmup, February 18, 2009; 3.8s | randychiu, [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/). Commons records a Flickr license review on May 23, 2010. | Small real-video model test. Not current fantasy evidence. |
| [Slovenia / Poland possession](https://commons.wikimedia.org/wiki/File:Domen_Lorbek_to_Brezec_-_Slovenia_vs_Poland.webm) | Domen Lorbek / Primoz Brezec, EuroBasket 2009; 5s | AnAvailibleUsername, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). Commons records a YouTube license review on March 29, 2013. | Alternate archival possession test. Not current fantasy evidence. |

Preserve the source page, creator, license link, recorded date and conversion/crop
notes with any derived clip. A catalog's listed license is provenance evidence;
it is not a blanket license for unrelated broadcasts or third-party uploads.
Neither historical player should be relabeled as a current fictional free agent.

Original file URLs observed on the source pages:

- Kobe: `https://upload.wikimedia.org/wikipedia/commons/8/83/Kobe_Bryant.ogv`
- Slovenia/Poland: `https://upload.wikimedia.org/wikipedia/commons/a/ae/Domen_Lorbek_to_Brezec_-_Slovenia_vs_Poland.webm`

Local download/conversion status lives in ignored `data/cache/licensed/`.
Downloads receive bounded requests and honor server Retry-After responses; no
alternate identities, proxy rotation, or access-control workarounds are used.
The Kobe download returned HTTP 429, including after one bounded retry following
the server's Retry-After guidance. No sample was downloaded or converted.

## ESPN and social discovery

- [ESPN NBA highlights](https://www.espn.com/watch/collections/9160566c-1989-414b-83e6-906d0c9986af/nba-highlights)
- [ESPN: Bronny alley-oop clip](https://www.espn.com/video/clip/_/id/46826279)
- [SportsCenter public X profile](https://x.com/SportsCenter/with_replies)

These are discovery/viewing links. No permission for local extraction and model
processing was established, and they were not imported as analysis-ready clips.
The Reddit search returned removed highlight posts; no stable reusable video was
selected from those results. Links and embeds do not supply SAM with video bytes.

[X's terms](https://x.com/en/tos) describe restrictions on automated scraping.
[Reddit's Data API terms](https://redditinc.com/policies/data-api-terms) require
respecting content-owner restrictions. [Disney's US terms](https://disneytermsofuse.com/english/)
cover ESPN-branded products. Private local use alone does not establish the
processing rights required by TapeGrade's original project requirements.

Current fantasy scouting still requires a recent permitted clip whose player
identity matches the player metadata. These archives address integration testing,
not licensed current NBA video/statistics coverage.
