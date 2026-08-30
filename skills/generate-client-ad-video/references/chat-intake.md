# Chat Intake Contract

Convert conversation facts to a UTF-8 JSON object and pass it to `project_workflow.py ingest`. Use canonical keys only:

```json
{
  "project_name": "Product launch",
  "offering": "Client-provided product description",
  "selling_points": ["Only verified claims"],
  "objective": "Introduce the product",
  "cta": "Learn more",
  "brand": "Optional",
  "audience": "Optional",
  "language": "English",
  "visual_style": "Optional",
  "must_preserve": ["Optional visible details"],
  "prohibited_claims": ["Optional restrictions"],
  "duration_seconds": 15,
  "aspect_ratio": "9:16",
  "quality": "high",
  "workspace_id": "optional UUID",
  "asset_roles": [
    {
      "filename": "original-upload-name.jpg",
      "role": "hero product",
      "must_preserve": "shape and color",
      "notes": "main visual"
    }
  ]
}
```

Required fields are `project_name`, `offering`, `selling_points`, `objective`, and `cta`. Defaults are 15 seconds, `9:16`, and `high`. Use attachment basenames in `asset_roles`; the ingest command remaps sanitized reserved filenames automatically.

Run:

```text
python scripts/project_workflow.py ingest WORKSPACE_ROOT --brief-json BRIEF_JSON --image IMAGE_1 --image IMAGE_2
```

The command never overwrites an existing project. It derives a safe directory name and appends `-02`, `-03`, and so on when needed. It copies PNG, JPEG, and WebP files into the new project root. A source attachment named `approved-keyframe.*` is renamed with a `source-` prefix so it cannot accidentally become a replacement keyframe.
