/**
 * M2.5 RC4 pre-release polish: user-facing findings from the M2.4 audit.
 *
 *   F1/F5  the upload hint states the limit the server actually enforces
 *          (published in /api/meta), never a number of its own;
 *   F2     every bundled sample in GET /api/sample-datasets is reachable
 *          from the UI, and the catalog is the only source of sample ids;
 *   F3     the results table says it is a preview of the first rows and
 *          that the exports carry the complete result;
 *   F4     the chromosome source never claims to detect an assembly, and a
 *          naming target without an assembly or a custom mapping blocks the
 *          run with a hint instead of a runtime error;
 *   F8     a re-uploaded dataset never leaves an old result on screen.
 */

import { beforeAll, afterEach, describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import App from './App.jsx';

beforeAll(() => {
  if (!window.ResizeObserver) {
    window.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const jsonResponse = (payload, { status = 200, ok = true } = {}) => ({
  ok,
  status,
  text: async () => JSON.stringify(payload),
  json: async () => payload,
});

const ASSEMBLIES = [
  {
    id: 'GRCh38',
    display_label: 'Human — Dec. 2013 (GRCh38/hg38)',
    scientific_name: 'Homo sapiens',
    ucsc_db: 'hg38',
  },
];

const NAMING_OPTIONS = [
  { key: null, label: 'Keep original names' },
  { key: 'ensembl', label: 'Ensembl names' },
  { key: 'ucsc', label: 'UCSC names' },
];

const SAMPLE_CATALOG = [
  {
    id: 'gene_overlap',
    name: 'Gene Overlap Analysis',
    mode: 'overlap',
    description: 'Exemplary BED query intervals matched against Ensembl GFF3 gene models.',
  },
  {
    id: 'closest_variants',
    name: 'Closest Variants Proximity',
    mode: 'closest',
    description: 'High-throughput VCF variation dataset paired with nearest gene proximity search.',
  },
  {
    id: 'stranded_features',
    name: 'Strand-Specific Features',
    mode: 'overlap',
    description: 'Strand-aware genomic intervals filtering for antisense/sense overlaps.',
  },
];

const metaWith = (maxFileSizeMb) => ({
  version: '9.9.9-test',
  default_engine: 'bedtools',
  max_file_size_mb: maxFileSizeMb,
  assemblies: ASSEMBLIES,
  naming_options: NAMING_OPTIONS,
  modes: [
    { key: 'overlap', label: 'Overlap' },
    { key: 'contains', label: 'Contains' },
    { key: 'within', label: 'Within' },
    { key: 'closest', label: 'Closest' },
  ],
});

const dataset = (filename, format, totalRows, revision) => ({
  filename,
  format,
  total_rows: totalRows,
  columns: ['chr', 'start', 'end'],
  preview: [{ chr: 'chr1', start: 9, end: 20 }],
  needs_mapping: false,
  ...(revision ? { revision } : {}),
});

const EXEC_RESULT = {
  status: 'success',
  result_revision: 'result-rev-1',
  query_revision: 'query-rev-1',
  annot_revision: 'annot-rev-1',
  registry: { source: 'none', revision: null, digest: null, name: null, row_count: null, assembly: null },
  stats: {
    elapsed_seconds: 0.42,
    engine: 'bedtools',
    mode: 'overlap',
    join: 'left',
    matched_query_count: 2,
    query_count: 2,
    result_count: 2,
    unmatched_query_count: 0,
    match_rate: 100,
  },
  warnings: [],
  feature_filter: null,
  gene_list: { gene_column: null, genes: [], top10: [] },
  chromosome_normalization: null,
  columns: ['coord_chr', 'coord_start', 'coord_end', 'has_overlap'],
  preview: [
    { coord_chr: 'chr1', coord_start: 9, coord_end: 20, has_overlap: true },
    { coord_chr: 'chr1', coord_start: 19, coord_end: 30, has_overlap: true },
  ],
  total_rows: 2,
  charts: { chromosome_distribution: [], match_ratio: [] },
};

// A backend that serves the metadata, the sample catalog and the dataset and
// execution endpoints, and records what was requested.
const backend = ({
  meta = metaWith(500),
  samples = SAMPLE_CATALOG,
  loadSample = null,
  execute = EXEC_RESULT,
  upload = dataset('q.bed', 'bed', 2, 'query-rev-1'),
} = {}) => {
  const calls = { sampleLoads: [], executes: [], uploads: [] };
  const fetchStub = vi.fn((url, options = {}) => {
    const u = String(url);
    if (u === '/api/meta') return Promise.resolve(jsonResponse(meta));
    if (u === '/api/sample-datasets') return Promise.resolve(jsonResponse(samples));
    if (u === '/api/load-sample') {
      calls.sampleLoads.push(options.body.get('sample_id'));
      return Promise.resolve(jsonResponse(loadSample ?? {
        query: { ...dataset('example_coordinates.bed', 'bed', 6, 'sample-query-rev'), coordinate_system: '0-based' },
        annot: { ...dataset('example_annotations.gff3', 'gff3', 6, 'sample-annot-rev'), coordinate_system: '1-based' },
      }));
    }
    if (u === '/api/upload') {
      calls.uploads.push({ role: options.body.get('role'), name: options.body.get('file')?.name });
      return Promise.resolve(jsonResponse(upload));
    }
    if (u === '/api/execute') {
      calls.executes.push(JSON.parse(options.body));
      return Promise.resolve(jsonResponse(execute));
    }
    if (u === '/api/dataset/clear') {
      return Promise.resolve(jsonResponse({ status: 'success', cleared: 'query', was_loaded: true }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchStub);
  return { calls, fetchStub };
};

const renderApp = async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText('v9.9.9-test')).toBeTruthy());
};

const fileInputs = () => document.querySelectorAll('input[type="file"]');

const uploadQuery = (name = 'q.bed') => {
  fireEvent.change(fileInputs()[0], {
    target: { files: [new File(['chr1\t10\t20\n'], name)] },
  });
};

const uploadAnnot = (name = 'a.gff3') => {
  fireEvent.change(fileInputs()[1], {
    target: { files: [new File(['chr1\t1\t20\n'], name)] },
  });
};

const runButton = () => screen.getByRole('button', { name: 'Run annotation' });

const selectWithOption = (text) => {
  const select = screen.getAllByRole('combobox').find((s) =>
    Array.from(s.options).some((o) => o.textContent.trim() === text),
  );
  if (!select) throw new Error(`no select with option ${text}`);
  return select;
};

const chooseOption = (text) => {
  const select = selectWithOption(text);
  const option = Array.from(select.options).find((o) => o.textContent.trim() === text);
  fireEvent.change(select, { target: { value: option.value } });
  return select;
};

const assemblySelect = () => selectWithOption('Custom chromosome mapping');
const sampleSelect = () => screen.getByLabelText('Bundled sample dataset');

// ---------------------------------------------------------------------------
// F1 / F5: the upload hint states the limit the server enforces
// ---------------------------------------------------------------------------

describe('M2.5 F1/F5: the upload hint follows the server limit', () => {
  it('states the limit published by /api/meta', async () => {
    backend({ meta: metaWith(500) });
    await renderApp();
    await waitFor(() => expect(screen.getAllByText(/500MB per file/).length).toBeGreaterThan(0));
  });

  it('follows a different configured limit instead of a hard-coded number', async () => {
    backend({ meta: metaWith(37) });
    await renderApp();
    await waitFor(() => expect(screen.getAllByText(/37MB per file/).length).toBeGreaterThan(0));
    expect(screen.queryByText(/500MB per file/)).toBeNull();
  });

  it('never claims a limit of its own when the server publishes none', async () => {
    const meta = metaWith(500);
    delete meta.max_file_size_mb;
    backend({ meta });
    await renderApp();
    await waitFor(() =>
      expect(screen.getAllByText(/Per-file size limit/).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/500MB per file/)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// F2: every bundled sample is reachable
// ---------------------------------------------------------------------------

describe('M2.5 F2: every bundled sample is reachable from the UI', () => {
  it('lists the samples from GET /api/sample-datasets', async () => {
    backend();
    await renderApp();
    const select = sampleSelect();
    await waitFor(() =>
      expect(Array.from(select.options).map((o) => o.value)).toEqual([
        'gene_overlap',
        'closest_variants',
        'stranded_features',
      ]),
    );
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      'Gene Overlap Analysis',
      'Closest Variants Proximity',
      'Strand-Specific Features',
    ]);
  });

  it.each([
    ['gene_overlap', 'example_coordinates.bed'],
    ['closest_variants', 'example_closest_variants.vcf'],
    ['stranded_features', 'example_strand_coordinates.bed'],
  ])('loads %s when it is selected', async (id, filename) => {
    const b = backend({
      loadSample: {
        query: { ...dataset(filename, 'bed', 6, 'sample-query-rev'), coordinate_system: '0-based' },
        annot: { ...dataset('example_annotations.gff3', 'gff3', 6, 'sample-annot-rev'), coordinate_system: '1-based' },
      },
    });
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());
    fireEvent.change(sampleSelect(), { target: { value: id } });
    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(b.calls.sampleLoads).toEqual([id]));
    await waitFor(() => expect(screen.getByText(filename)).toBeTruthy());
  });

  it('follows the operation the catalog declares for the sample', async () => {
    const b = backend();
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBeTruthy());
    fireEvent.change(sampleSelect(), { target: { value: 'closest_variants' } });
    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(b.calls.sampleLoads).toEqual(['closest_variants']));
    // The operation select now shows the catalog's declared operation.
    const modeSelect = selectWithOption('Overlap');
    expect(modeSelect.value).toBe('closest');
  });

  it('never names a sample the catalog does not list', async () => {
    const b = backend({ samples: [SAMPLE_CATALOG[1]] });
    await renderApp();
    await waitFor(() => expect(sampleSelect().value).toBe('closest_variants'));
    fireEvent.click(screen.getByRole('button', { name: /load sample data/i }));
    await waitFor(() => expect(b.calls.sampleLoads).toEqual(['closest_variants']));
  });
});

// ---------------------------------------------------------------------------
// F3: the results table says it is a preview
// ---------------------------------------------------------------------------

describe('M2.5 F3: the results table is labelled as a preview', () => {
  it('states the preview size and that the exports carry the complete result', async () => {
    backend();
    await renderApp();
    uploadQuery();
    uploadAnnot();
    await waitFor(() => expect(runButton().disabled).toBe(false));
    fireEvent.click(runButton());
    await waitFor(() => expect(screen.getByText(/Analysis complete/)).toBeTruthy());

    const note = screen.getByText(/Preview: this table shows only the first/);
    expect(note).toBeTruthy();
    expect(note.textContent).toMatch(/100/);
    expect(note.textContent).toMatch(/complete result/i);
    expect(note.textContent).toMatch(/Display Filter applies to this preview/i);
  });
});

// ---------------------------------------------------------------------------
// F4: the assembly selector never claims to detect an assembly
// ---------------------------------------------------------------------------

describe('M2.5 F4: the chromosome source is explicit, never detected', () => {
  it('does not offer an "Auto-detect" genome assembly', async () => {
    backend();
    await renderApp();
    const select = assemblySelect();
    const first = Array.from(select.options)[0];
    expect(first.textContent).toMatch(/No assembly/i);
    expect(first.textContent).not.toMatch(/auto-detect/i);
    expect(Array.from(select.options).map((o) => o.textContent).join(' ')).not.toMatch(
      /Auto-detect/i,
    );
  });

  it('blocks the run and explains why when a naming target has no assembly', async () => {
    backend();
    await renderApp();
    uploadQuery();
    uploadAnnot();
    await waitFor(() => expect(runButton().disabled).toBe(false));

    chooseOption('Ensembl names');
    expect(runButton().disabled).toBe(true);
    expect(
      screen.getByText(/Select a genome assembly, or keep the original chromosome names/),
    ).toBeTruthy();
  });

  it('allows the run once a bundled assembly is selected', async () => {
    const b = backend();
    await renderApp();
    uploadQuery();
    uploadAnnot();
    await waitFor(() => expect(runButton().disabled).toBe(false));

    chooseOption('Ensembl names');
    expect(runButton().disabled).toBe(true);

    chooseOption('Human — Dec. 2013 (GRCh38/hg38)');
    expect(runButton().disabled).toBe(false);

    fireEvent.click(runButton());
    await waitFor(() => expect(b.calls.executes.length).toBe(1));
    expect(b.calls.executes[0]).toMatchObject({ assembly: 'GRCh38', chr_naming: 'ensembl' });
  });

  it('keeps the original names runnable without any assembly', async () => {
    const b = backend();
    await renderApp();
    uploadQuery();
    uploadAnnot();
    await waitFor(() => expect(runButton().disabled).toBe(false));
    fireEvent.click(runButton());
    await waitFor(() => expect(b.calls.executes.length).toBe(1));
    expect(b.calls.executes[0]).toMatchObject({ assembly: null, chr_naming: null });
  });

  it('blocks the run when a custom mapping is selected but missing', async () => {
    backend();
    await renderApp();
    uploadQuery();
    uploadAnnot();
    await waitFor(() => expect(runButton().disabled).toBe(false));
    chooseOption('Custom chromosome mapping');
    chooseOption('Ensembl names');
    expect(runButton().disabled).toBe(true);
    expect(
      screen.getByText(/Upload a custom chromosome mapping, or keep the original chromosome names/),
    ).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// F8: a re-uploaded dataset never leaves an old result on screen
// ---------------------------------------------------------------------------

describe('M2.5 F8: a re-upload withdraws the previous result', () => {
  it('clears the displayed result when the query file is replaced', async () => {
    backend();
    await renderApp();
    uploadQuery('q.bed');
    uploadAnnot('a.gff3');
    await waitFor(() => expect(runButton().disabled).toBe(false));
    fireEvent.click(runButton());
    await waitFor(() => expect(screen.getByText(/Analysis complete/)).toBeTruthy());
    expect(screen.getByText('coord_chr')).toBeTruthy();

    // A new upload for the same side withdraws the result: the old table must
    // never stay on screen as if it belonged to the new dataset.
    uploadQuery('q2.bed');
    await waitFor(() => expect(screen.getByText(/Uploading and parsing q2.bed/)).toBeTruthy());
    expect(screen.queryByText('coord_chr')).toBeNull();
    expect(screen.getByText(/No results yet/)).toBeTruthy();
  });

  it('clears the displayed result when the annotation file is replaced', async () => {
    backend();
    await renderApp();
    uploadQuery('q.bed');
    uploadAnnot('a.gff3');
    await waitFor(() => expect(runButton().disabled).toBe(false));
    fireEvent.click(runButton());
    await waitFor(() => expect(screen.getByText(/Analysis complete/)).toBeTruthy());

    uploadAnnot('a2.gff3');
    await waitFor(() => expect(screen.getByText(/Uploading and parsing a2.gff3/)).toBeTruthy());
    expect(screen.queryByText('coord_chr')).toBeNull();
    expect(screen.getByText(/No results yet/)).toBeTruthy();
  });
});
