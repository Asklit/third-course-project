export type MaterialAsset = {
  id: string;
  url: string;
  type: string;
  caption: string;
};

export type WikiSection = {
  id: string;
  title: string;
  kind: string;
  order: number;
  content_md: string;
  tags: string[];
  assets: MaterialAsset[];
};

export type WikiLabSummary = {
  lab_id: number;
  slug: string;
  title: string;
  tags: string[];
  sections_count: number;
};

export type WikiLabDetails = WikiLabSummary & {
  source_file: string;
  updated_at: string;
  stats: Record<string, number>;
  sections: WikiSection[];
  assets: MaterialAsset[];
};

export type WikiSearchHit = {
  lab_slug: string;
  lab_title: string;
  section_id: string;
  section_title: string;
  kind: string;
  snippet: string;
  tags: string[];
};

export type WikiSearchResponse = {
  total: number;
  items: WikiSearchHit[];
};
