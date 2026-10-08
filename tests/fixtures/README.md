# Test fixtures

## Synthetic clips

`make_clips.py` generates the video clips at test time (moving, black, frozen boxes). No
people, no real footage. Only the script is committed.

## A5 still images (phase 02, `tests/edge/test_detector_slow.py`)

Downloaded by the slow test on first run to `tests/fixtures/downloads/` (gitignored), and
checked against the SHA-1 that Wikimedia Commons publishes for the original file. They are
not committed: CLAUDE.md rule 9 keeps photos of real people out of the repository.

| File | People | Source | Author | Licence |
|---|---|---|---|---|
| `apollo11_crew.jpg` | 3 (large, unoccluded, cut at the thighs) | <https://commons.wikimedia.org/wiki/File:Apollo_11_Crew.jpg> | NASA | Public domain (work of the US federal government). NASA insignia in the image have their own use restrictions; this is test use only |
| `breese_gym.jpg` | 0 (building exterior, lamp post, trees) | <https://commons.wikimedia.org/wiki/File:Breese_Gymnasium,_Western_Carolina_University,_Cullowhee,_NC_(46640519431).jpg> | Warren LeMay | CC0 1.0 |

Expected counts and the tolerance (0) are constants in the test.
