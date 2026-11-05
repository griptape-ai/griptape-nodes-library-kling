- Kling nodes report failures as structured node errors. The editor shows Kling's own message, with
  the status code, Kling error code, request ID, task ID and response body under More info. Messages
  no longer carry the node name or a pasted response. A missing key reports first and on its own,
  with a link to Settings and to Kling's API key page. A key Kling refuses (HTTP 401) links to
  Settings only. A half-set Access Key / Secret Key pair links to Settings only. The library now
  requires Griptape Nodes 0.105.0 or later.
  [#30](https://github.com/griptape-ai/griptape-nodes-library-kling/issues/30)
