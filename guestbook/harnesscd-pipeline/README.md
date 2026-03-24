## Harness CD Pipeline

### Simplified workflow (Git as source of truth)

1. **Bootstrap once** (connectors, secret, env, infra, service, Git-backed pipeline), e.g. with
   `guestbook_harness_bootstrap.py` in your Harness tooling repo, or apply the YAMLs/APIs manually.
2. Configure the **`guestbook_rolling_pipeline`** pipeline in Harness as **stored in Git (REMOTE)** for
   `rolling-pipeline.yml` on your branch. After that, **push commits to GitHub**, then either:
   - **Run** the pipeline from the Harness UI (Harness loads the latest pipeline YAML from Git for that run), or
   - Enable **`.github/workflows/harness-guestbook-cd.yml`** and add repo secrets `HARNESS_API_KEY` and
     `HARNESS_ACCOUNT_ID` so a push under `guestbook/` can trigger a run automatically.
3. **Kubernetes manifests** referenced by the service (`guestbook/*.yaml`) are already fetched from Git on
   each deployment, as long as the **branch** in `service.yml` matches the branch you push to.

Keep the **same branch** in `service.yml` and in your Harness Git settings / bootstrap env (`HARNESS_GIT_BRANCH`).

### Original manual order (inline / first-time YAML apply)

Run the resource yaml's in the below order in order to create the required objects and pipeline and execute it successfully.

1. github-connector.yml
2. kubernetes-connector.yml
3. environment.yml
4. infrastructure-definition.yml
5. service.yml
6. canary-pipeline.yml
        OR
   bluegreen-pipeline.yml
        OR
   rolling-pipeline.yml
