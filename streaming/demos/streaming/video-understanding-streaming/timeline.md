# Realtime video-understanding timeline

Producer:
[`OpenMOSS-Team/openmoss-team-moss-vl-realtime`](https://huggingface.co/spaces/OpenMOSS-Team/openmoss-team-moss-vl-realtime)

Input: a 5.088-second MIT-licensed clip from
`zirui3/tiny-video-samples`. Its dataset caption describes a cloudy night sky,
a crescent moon, and two flying birds.

The producer's original deployment rejected every call because its effective
ZeroGPU reservation was 270 seconds, above the platform maximum. The exact
Space was temporarily duplicated and only:

```diff
-@spaces.GPU(duration=180)
+@spaces.GPU(duration=80)
```

was changed. The source diff is retained in `source/temporary_space.patch`.
The temporary Space was permanently deleted after capture.

| Observation | Elapsed |
|---|---:|
| Frame 1 observed | 8.237 s |
| Frame 11 observed | 8.325 s |
| First generated control token | 12.637 s |
| First lexical answer content | 12.713 s |
| Complete answer snapshot | 14.779 s |
| Application `done` | 23.401 s |
| Transport terminal payload | 23.556 s |

The stream contains:

- 11 `observing` snapshots, one after each sampled frame
- 38 changing answer snapshots
- 51 total content/status updates, including repeats and terminal values

Final answer:

> A dark, cloudy night sky with a crescent moon is visible, and two winged,
> dragon-like creatures fly from the left toward the right, passing in front
> of the moon.

The model called the silhouettes “dragon-like creatures” rather than birds,
but otherwise matched the dataset caption's scene and motion.

In this capture all 11 frames were pushed before the model emitted text. The
evidence therefore demonstrates separate `observing` and `responding` phases,
not simultaneous frame ingestion and lexical output in this particular run.
