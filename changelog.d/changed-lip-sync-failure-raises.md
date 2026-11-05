- **Breaking:** `Kling AI Lip Sync` stops the run with an error when Kling reports the task as
  failed. It used to return an empty video and put `FAILED: <reason>` in `task_id`, so the run
  looked successful. Nodes that read that output need to handle the error instead.
  [#30](https://github.com/griptape-ai/griptape-nodes-library-kling/issues/30)
