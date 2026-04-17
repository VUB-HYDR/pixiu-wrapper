# pixiu-wrapper

A small Python wrapper around VUB Pixiu S3-compatible storage.

## Install

Install from your private GitHub repository URL:

```bash
pip install "git+ssh://git@github.com/<org>/<repo>.git"
```

## CLI

Run interactive setup once:

```bash
pixiu setup
```

This creates (or updates) the local config file at `~/.pixiu/config.toml`.

You can also run setup non-interactively:

```bash
pixiu setup \
	--endpoint https://pixiu.vub.be \
	--access-key YOUR_ACCESS_KEY \
	--secret-key YOUR_SECRET_KEY \
	--alias project1 \
	--bucket hydr-bgw-project1
```

Add another bucket alias:

```bash
pixiu add-bucket project1 hydr-bgw-project1
```

Example with a second alias:

```bash
pixiu add-bucket project2 hydr-bgw-project2
```

Browse bucket contents from CLI:

```bash
# List root of bucket alias
pixiu ls project1

# List one folder deeper
pixiu ls project1 next_folder

# Render full tree from bucket root
pixiu tree project1

# Render tree from a specific prefix
pixiu tree project1 next_folder
```

## Usage

After setup, use aliases in your code (for example `project1`) instead of real bucket names.

## Python usage

```python
import pixiu as pi

store = pi.PixiuStore("project1")

df = store.get_from_csv("data/table.csv")
ds = store.get_from_nc("data/field.nc")

# Forward pandas.read_csv kwargs for non-standard CSV files
swap_df = store.get_from_csv("data/input/result_output.csv", comment="*", parse_dates=["DATETIME"])

store.upload("./local/file.txt", "uploads/file.txt")
store.download(key="uploads/file.txt", local_path="./downloads/file.txt")
store.download(prefix="uploads/", local_dir="./downloads_all")

directories, files = store.ls("uploads")
print("directories:", directories)
print("files:", files)

tree_lines = store.tree("uploads")
print("\n".join(tree_lines))

# Create folder markers through s3fs wrappers
store.mkdir("uploads/2026")
store.makedirs("uploads/2026/04", exist_ok=True)
```

### Download modes

Single object download:

```python
store.download(key="path/in/bucket.txt", local_path="./local/out.txt")
```

Prefix download (recursive into a local directory):

```python
paths = store.download(prefix="model-runs/", local_dir="./runs")
print(f"Downloaded {len(paths)} files")
```

### Optional disk cache

By default, reads are cached in memory. To persist cache between runs, provide `cache_dir`:

```python
store = pi.PixiuStore("project1", cache_dir=".pixiu-cache")
df = store.get_from_csv("large/table.csv")
```

Clear cache manually when needed:

```python
store.clear_cache()
```

### Common errors

- Missing config: run `pixiu setup` first.
- Unknown alias: add it with `pixiu add-bucket <alias> <bucket>`.
- Invalid download call: pass either `key` and `local_path`, or `prefix` and `local_dir`.

## Config shape

```toml
[default]
endpoint_url = "https://pixiu.vub.be"
access_key = "..."
secret_key = "..."

[default.buckets]
project1 = "hydr-bgw-project1"
project2 = "hydr-bgw-project2"
```

## Testing

Use the Makefile target:

```bash
make test
```
