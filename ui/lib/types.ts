// Wire types mirroring the FastAPI schemas (snake_case, as the API returns them).

export type Persona = {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
};

export type Health = {
  // Provenance the banner states on every page: where the runtime sits and which model
  // answers. Both come from the service; nothing in the console infers either.
  runtime: string;
  generator_model: string;
  status: string;
  profile: string;
  region: string;
};

export type Approval = {
  checker: string;
  reason: string;
};

export type ReviewItem = {
  review_id: string;
  tenant: string;
  source_key: string;
  action: string;
  maker: string;
  subject: string;
  summary: string;
  severity: string;
  required_approvals: number;
  sod_group: string;
  case_ref: string;
  state: string;
  approvals_count: number;
  approvals: Approval[];
  citations: { source_id: string; title: string; snippet: string }[];
};

export type Disposition = "approve" | "reject" | "amend";

export type DecisionResponse = {
  decision: string;
  findings: string[];
  item: ReviewItem;
};
