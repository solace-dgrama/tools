# Finding Commits Between Two Builds

## Step 1: Get the Git Commit for Each Build

### Option A: From the Results Page

On the AFW results page for a load, click the link next to **commit:** to open the
GitHub commit history at that exact SHA.

### Option B: From Jenkins

```
https://jenkins.solacedev.net/job/pubsubplus_git/job/<branch>/<loadNumber>/
```

The load number is the last component of the load version (e.g. `6067` from `100.0main.0.6067`).
For feature branches, the `/` in the branch name must be double-encoded as `%252F`:

```
https://jenkins.solacedev.net/job/pubsubplus_git/job/10.25.0/76/
https://jenkins.solacedev.net/job/pubsubplus_git/job/feature%252FSOL-108193/10/
```

### Option C: From the Build Log

```bash
grep GIT_COMMIT /home/public/RND/loads/solcbr/main/<load>/logs/build.log
```

Example:

```bash
grep GIT_COMMIT /home/public/RND/loads/solcbr/main/100.0main.0.6067/logs/build.log
# GIT_COMMIT=3edbde69e340f49ae87042b7b9aba3e6d087180a

grep GIT_COMMIT /home/public/RND/loads/solcbr/main/100.0main.0.6337/logs/build.log
# GIT_COMMIT=294b1f1211dc9acd859c876f66566ebdd4934281
```

## Step 2: List Commits Between the Two SHAs

```bash
git log <older-sha>..<newer-sha>
```

Example:

```bash
git log 3edbde69e340f49ae87042b7b9aba3e6d087180a..294b1f1211dc9acd859c876f66566ebdd4934281
```
