# Real Vercel Preview and private Blob trial

This trial deployed the unmodified application at `62badef1d608d94903da475bfd2b689cb80f9c49` to a new disposable project. The application used a newly created private Blob store in iad1, an independent reviewer identity and two synthetic workers. Vercel deployment protection used one project-scoped automation credential. The Blob token and the five application environment variables were present only in Preview. No existing lab credentials or data were used.

## Reproduction

The common harness supplies the protocol, uploads, analysis submissions, simultaneous claimants and numerical expectations. These commands require a Vercel CLI session with permission on the selected team and sufficient included usage. Run them from the `lab-factory/` directory of the trial release. Use a new project, new store and an unused origin for every run. Discard the credentials after cleanup.

```sh
uv sync --locked
trialdir="$PWD/benchmarks/deployment_trials/variants/vercel_preview"
scratch=$(mktemp -d)
suffix=$(python3 -c 'import secrets; print(secrets.token_hex(5))')
project="lf-trial-$suffix"
domain="lf-check-$suffix.vercel.app"
origin="https://$domain"
scope=YOUR_VERCEL_TEAM_SLUG
mkdir "$scratch/export"
git archive --format=tar --output="$scratch/source.tar" 62badef:lab-factory
tar -xf "$scratch/source.tar" -C "$scratch/export"
vercel project add "$project" --scope "$scope"
vercel link --cwd "$scratch/export" --project "$project" --scope "$scope" --yes
vercel blob create-store "$project" --access private --region iad1 --environment preview --yes --cwd "$scratch/export" --scope "$scope"
vercel env ls preview --cwd "$scratch/export" --scope "$scope"
trial() {
  uv run --locked python "$trialdir/trial.py" "$1" --export "$scratch/export" --scratch "$scratch" --scope "$scope" --project "$project" --origin "$origin"
}
trial configure
vercel deploy --target=preview --yes --scope "$scope" --cwd "$scratch/export"
```

In the recorded run Vercel treated the very first deployment of a fresh project as its initial production deployment, despite the Preview flag. It had no trial credentials or data. Check the deployment output. When that happens, issue a second deployment with `--target=preview --force --with-cache`. Confirm the resulting deployment is marked **Preview** before sending any requests. Verify that the alias is unused, then take the first Preview's ID and URL from that command.

```sh
vercel alias set "$first_preview_url" "$domain" --scope "$scope"
trial run
vercel deploy --target=preview --yes --force --with-cache --cwd "$scratch/export" --scope "$scope"
vercel remove "$first_preview_id" --yes --scope "$scope"
trial offline
vercel alias set "$second_preview_url" "$domain" --scope "$scope"
trial verify
```

The second Preview uses the same private store and application source. Keep the origin unbound until the offline probe witnesses the provider's deletion response. The two builds can coexist before the first deployment is removed. The fault test measures disappearance of the first deployment and recovery from the retained state through a different deployment.

After saving the sanitized result, remove only the store and project assigned to this trial. Supply the exact private store ID reported by `create-store` and the project ID in this run’s `.vercel/project.json`. The project deletion also retires test aliases, deployments, environment variables and its automation credential. Verify the store and project are absent using their respective IDs. The scratch directory contains the retired test credentials and provider-generated local environment file.
