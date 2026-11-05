- **Breaking:** `Kling AI Motion Control` stops the run with an error for a missing prompt, image or
  video, a failed task, a timeout, a failed status check and a response with no video. These used to
  set the status text and end the run normally. A wired `Failed` output behaves as before. With
  `Failed` unwired, the node now errors, so add a `Failed` connection where a failure should not stop the
  workflow.
  [#30](https://github.com/griptape-ai/griptape-nodes-library-kling/issues/30)
