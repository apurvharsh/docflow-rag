const { createElement: h, useEffect, useRef, useState } = React;

const stages = [
    'Intake', 'Discovery', 'Requirements', 'Planning', 'Architecture',
    'Design', 'Development', 'Integration', 'Quality Assurance',
    'User Acceptance Testing', 'Release', 'Operations', 'Maintenance', 'Retirement'
];

const documentTypes = [
    'PRD', 'BRD', 'SRS', 'Architecture Document', 'Design Document', 'ADR',
    'API Specification', 'User Story', 'Use Case', 'Project Plan', 'Risk Register',
    'Test Plan', 'Test Case', 'Test Report', 'Release Notes', 'Runbook',
    'Standard Operating Procedure', 'Security Review', 'Compliance Document',
    'Meeting Notes', 'Contract', 'Proposal', 'Other'
];

const fileTypes = '.txt,.md,.json,.pdf,.doc,.docx,.ppt,.pptx';

async function apiFetch(url, options = {}) {
    const token = localStorage.getItem('docflow_token');
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401 && token) {
        localStorage.removeItem('docflow_token');
        window.dispatchEvent(new Event('docflow-logout'));
    }
    return response;
}

async function openAuthorizedFile(documentId) {
    const popup = window.open('', '_blank');
    const response = await apiFetch(`/documents/${encodeURIComponent(documentId)}/open`);
    if (!response.ok) {
        if (popup) popup.close();
        throw new Error(`Could not open document (${response.status})`);
    }
    const blobUrl = URL.createObjectURL(await response.blob());
    if (popup) popup.location = blobUrl;
    else window.open(blobUrl, '_blank', 'noopener,noreferrer');
}

async function openAuthorizedSqliteRecord(documentId) {
    const popup = window.open('', '_blank');
    const response = await apiFetch(`/database/documents/${encodeURIComponent(documentId)}`);
    const data = await response.json();
    if (!response.ok) {
        if (popup) popup.close();
        throw new Error(data.detail || `Could not open SQLite record (${response.status})`);
    }
    if (!popup) return;
    popup.document.title = 'DocFlow SQLite Record';
    popup.document.body.innerHTML = '<pre style="white-space:pre-wrap;font:14px monospace;padding:24px"></pre>';
    popup.document.querySelector('pre').textContent = JSON.stringify(data, null, 2);
}

function Select({ name, options, defaultValue, ...props }) {
    return h('select', { name, defaultValue, ...props },
        options.map(option => typeof option === 'object'
            ? h('option', { key: option.value, value: option.value }, option.label)
            : h('option', { key: option, value: option }, option)
        )
    );
}

function Status({ message, type }) {
    return h('div', { className: `panel status ${type || ''}` },
        h('h3', null, 'Activity Feed'),
        h('p', null, message)
    );
}

function renderInlines(text) {
    if (!text) return '';
    // Matches **bold**, `code`, *italic*, and [Source N] citations
    const regex = /(\*\*.*?\*\*|`.*?`|\*[^\*]+?\*|\[Source\s*\d+[^\]]*\])/gi;
    const parts = text.split(regex);
    return parts.map((part, index) => {
        if (!part) return null;
        // **bold** -> remove ** and style
        if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
            return h('strong', { key: index, className: 'answer-bold' }, part.slice(2, -2));
        }
        // `code` -> remove ` and style
        if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
            return h('code', { key: index, className: 'inline-code' }, part.slice(1, -1));
        }
        // *italic* -> remove * and style
        if (part.startsWith('*') && part.endsWith('*') && part.length >= 2 && !part.startsWith('**')) {
            return h('em', { key: index }, part.slice(1, -1));
        }
        // [Source N] -> highlight as citation pill badge
        if (/^\[Source\s*\d+[^\]]*\]$/i.test(part)) {
            return h('span', { key: index, className: 'citation-pill' }, part);
        }
        return part;
    });
}

function FormattedAnswer({ text }) {
    if (!text) return null;
    const lines = text.split('\n');
    const elements = [];
    let currentList = null;

    function flushList() {
        if (currentList) {
            elements.push(
                h(currentList.type, { key: elements.length }, currentList.items)
            );
            currentList = null;
        }
    }

    lines.forEach((rawLine, idx) => {
        const trimmed = rawLine.trim();
        if (!trimmed) {
            flushList();
            return;
        }

        // Horizontal dividers
        if (/^(\-\-\-|\*\*\*|___)$/.test(trimmed)) {
            flushList();
            elements.push(h('hr', { key: idx, className: 'answer-divider' }));
            return;
        }

        // Headings (remove #, ##, ###, #### and render clean headings)
        if (trimmed.startsWith('#### ')) {
            flushList();
            elements.push(h('h4', { key: idx, className: 'answer-h3' }, renderInlines(trimmed.slice(5))));
            return;
        }
        if (trimmed.startsWith('### ')) {
            flushList();
            elements.push(h('h3', { key: idx, className: 'answer-h3' }, renderInlines(trimmed.slice(4))));
            return;
        }
        if (trimmed.startsWith('## ')) {
            flushList();
            elements.push(h('h2', { key: idx, className: 'answer-h2' }, renderInlines(trimmed.slice(3))));
            return;
        }
        if (trimmed.startsWith('# ')) {
            flushList();
            elements.push(h('h1', { key: idx, className: 'answer-h1' }, renderInlines(trimmed.slice(2))));
            return;
        }

        // Bullet list items (remove leading *, -, +)
        const bulletMatch = rawLine.match(/^(\s*)([\*\-\+])\s+(.*)$/);
        if (bulletMatch) {
            const indentSpaces = bulletMatch[1].length;
            const content = bulletMatch[3];
            const isSub = indentSpaces >= 2;

            if (!currentList || currentList.type !== 'ul') {
                flushList();
                currentList = { type: 'ul', items: [] };
            }
            currentList.items.push(
                h('li', {
                    key: idx,
                    className: isSub ? 'answer-sub-item' : 'answer-item'
                }, renderInlines(content))
            );
            return;
        }

        // Numbered list items
        const numMatch = rawLine.match(/^(\s*)\d+\.\s+(.*)$/);
        if (numMatch) {
            const content = numMatch[2];
            if (!currentList || currentList.type !== 'ol') {
                flushList();
                currentList = { type: 'ol', items: [] };
            }
            currentList.items.push(
                h('li', { key: idx, className: 'answer-item' }, renderInlines(content))
            );
            return;
        }

        // Standard paragraph
        flushList();
        elements.push(h('p', { key: idx }, renderInlines(trimmed)));
    });

    flushList();

    return h('div', { className: 'formatted-answer' }, elements);
}


function AuthPage({ onLogin }) {
    const [mode, setMode] = useState('signin');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [fullName, setFullName] = useState('');
    const [organization, setOrganization] = useState('');
    const [teamName, setTeamName] = useState('');
    const [jobTitle, setJobTitle] = useState('');
    const [managerEmail, setManagerEmail] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [demoBusy, setDemoBusy] = useState(false);

    async function submit(event) {
        if (event) event.preventDefault();
        setBusy(true);
        setError('');
        try {
            const isSignup = mode === 'signup';
            const payload = isSignup
                ? { email, password, full_name: fullName, organization, team_name: teamName, job_title: jobTitle, manager_email: managerEmail || null }
                : { email, password };
            const response = await fetch(isSignup ? '/signup' : '/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || (isSignup ? 'Account registration failed' : 'Invalid email or password'));
            if (isSignup || data.is_new_user) {
                localStorage.setItem('docflow_new_signup', 'true');
            }
            localStorage.setItem('docflow_token', data.access_token);
            onLogin(data.access_token);
        } catch (loginError) {
            setError(loginError.message);
        } finally {
            setBusy(false);
        }
    }

    async function demoLogin() {
        setDemoBusy(true);
        setError('');
        try {
            const response = await fetch('/auth/demo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Demo login failed');
            localStorage.setItem('docflow_token', data.access_token);
            onLogin(data.access_token);
        } catch (err) {
            setError(err.message);
        } finally {
            setDemoBusy(false);
        }
    }

    return h('div', { className: 'auth-page-wrapper' },
        h('div', { className: 'auth-container' },
            // Left Hero Showcase
            h('div', { className: 'auth-hero-pane' },
                h('div', null,
                    h('div', { className: 'auth-hero-brand' },
                        h('span', { className: 'mark' }),
                        h('span', null, 'DocFlow AI')
                    ),
                    h('div', { className: 'auth-hero-badge' }, '✨ RAG & Knowledge Workspace'),
                    h('h1', { className: 'auth-hero-title' }, 'Unified intelligence across all your project documentation.'),
                    h('p', { className: 'auth-hero-subtitle' },
                        'Ask questions, manage project documents, and work securely inside a role-aware knowledge workspace powered by Gemini and Qdrant hybrid search.'
                    ),
                    h('div', { className: 'auth-features-list' },
                        h('div', { className: 'auth-feature-item' },
                            h('span', { className: 'auth-feature-icon' }, '⚡'),
                            h('div', { className: 'auth-feature-text' },
                                h('strong', null, 'Hybrid Dense + Sparse Search'),
                                'Sub-millisecond vector retrieval with exact keyword and semantic understanding.'
                            )
                        ),
                        h('div', { className: 'auth-feature-item' },
                            h('span', { className: 'auth-feature-icon' }, '🤖'),
                            h('div', { className: 'auth-feature-text' },
                                h('strong', null, 'Grounded Gemini AI Q&A'),
                                'Synthesizes answers with verifiable citation pill badges and source relevance scoring.'
                            )
                        ),
                        h('div', { className: 'auth-feature-item' },
                            h('span', { className: 'auth-feature-icon' }, '🗄️'),
                            h('div', { className: 'auth-feature-text' },
                                h('strong', null, 'RBAC + ABAC Workspaces'),
                                'Admins manage tenant projects and roles; team members see only authorized project documents.'
                            )
                        ),
                        h('div', { className: 'auth-feature-item' },
                            h('span', { className: 'auth-feature-icon' }, '🌐'),
                            h('div', { className: 'auth-feature-text' },
                                h('strong', null, 'Open Files & SQLite Records'),
                                'Open authorized uploads in the browser and inspect their searchable SQLite metadata.'
                            )
                        ),
                        h('div', { className: 'auth-feature-item' },
                            h('span', { className: 'auth-feature-icon' }, '📊'),
                            h('div', { className: 'auth-feature-text' },
                                h('strong', null, 'Any Project Document'),
                                'Upload PDF, Word, PowerPoint, Markdown, text, and JSON files for structured retrieval.'
                            )
                        )
                    )
                ),
                h('div', { className: 'auth-hero-footer' },
                    h('span', null, 'DocFlow AI Platform v2.4'),
                    h('span', null, '🔒 Secure Token Authentication')
                )
            ),

            // Right Form Interactive Card
            h('div', { className: 'auth-form-pane' },
                h('div', { className: 'auth-tabs' },
                    h('button', {
                        type: 'button',
                        className: `auth-tab-btn ${mode === 'signin' ? 'active' : ''}`,
                        onClick: () => { setMode('signin'); setError(''); }
                    }, '🔑 Sign In'),
                    h('button', {
                        type: 'button',
                        className: `auth-tab-btn ${mode === 'signup' ? 'active' : ''}`,
                        onClick: () => { setMode('signup'); setError(''); }
                    }, '✨ Create Account')
                ),

                h('div', { className: 'auth-header' },
                    h('h2', null, mode === 'signin' ? 'Sign in to workspace' : 'Create your account'),
                    h('p', null, mode === 'signin'
                        ? 'Enter your credentials, continue with Google, or enter instantly with demo access.'
                        : 'Register your profile to unlock full workspace search and document ingestion.'
                    )
                ),

                // Google OAuth Button
                h('button', {
                    type: 'button',
                    className: 'google-button-full',
                    onClick: () => {
                        window.location.href = '/auth/google/start';
                    }
                },
                    h('svg', { className: 'google-icon', viewBox: '0 0 24 24' },
                        h('path', { fill: '#4285F4', d: 'M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z' }),
                        h('path', { fill: '#34A853', d: 'M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z' }),
                        h('path', { fill: '#FBBC05', d: 'M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z' }),
                        h('path', { fill: '#EA4335', d: 'M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z' })
                    ),
                    mode === 'signin' ? 'Continue with Google' : 'Sign up with Google'
                ),

                h('div', { className: 'auth-divider' }, 'or use email and password'),

                // Form
                h('form', { onSubmit: submit, style: { padding: 0 } },
                    mode === 'signup' && h('div', { className: 'fields', style: { gridTemplateColumns: '1fr 1fr', gap: 10, margin: '0 0 12px' } },
                        h('label', null, 'Full Name', h('input', { value: fullName, onChange: e => setFullName(e.target.value), placeholder: 'Jane Doe', required: true })),
                        h('label', null, 'Organization', h('input', { value: organization, onChange: e => setOrganization(e.target.value), placeholder: 'Acme Corp', required: true })),
                        h('label', null, 'Team', h('input', { value: teamName, onChange: e => setTeamName(e.target.value), placeholder: 'Engineering', required: true })),
                        h('label', null, 'Job Title', h('input', { value: jobTitle, onChange: e => setJobTitle(e.target.value), placeholder: 'Lead Architect', required: true })),
                        h('label', { className: 'wide' }, 'Manager Email (optional)', h('input', { value: managerEmail, onChange: e => setManagerEmail(e.target.value), type: 'email', placeholder: 'manager@acme.com' }))
                    ),
                    h('label', { style: { marginTop: 8 } }, 'Email Address',
                        h('input', { value: email, onChange: e => setEmail(e.target.value), type: 'email', placeholder: 'name@company.com', required: true })
                    ),
                    h('label', { style: { marginTop: 10 } }, 'Password',
                        h('input', { value: password, onChange: e => setPassword(e.target.value), type: 'password', placeholder: '••••••••', minLength: 8, required: true })
                    ),

                    mode === 'signin' && h('div', { className: 'quick-fill-hint' },
                        h('span', null, '💡 Quick fill sample:'),
                        h('span', {
                            className: 'quick-fill-chip',
                            onClick: () => { setEmail('alice@example.com'); setPassword('correct-password'); }
                        }, 'alice@example.com'),
                        h('span', {
                            className: 'quick-fill-chip',
                            onClick: () => { setEmail('admin'); setPassword('admin'); }
                        }, 'admin')
                    ),

                    error && h('div', { className: 'auth-error-alert', style: { marginTop: 12 } },
                        h('span', null, '⚠️'),
                        h('span', null, error)
                    ),

                    h('button', {
                        type: 'submit',
                        disabled: busy,
                        style: { marginTop: 16 }
                    }, busy ? 'Authenticating…' : mode === 'signin' ? 'Sign In to Workspace →' : 'Create Account & Enter →')
                ),

                // Instant Demo Access Card (for Everyone)
                mode === 'signin' && h('div', { className: 'instant-demo-card' },
                    h('div', { className: 'instant-demo-header' },
                        h('span', { className: 'instant-demo-title' }, '⚡ Super Admin Access'),
                        h('span', { className: 'instant-demo-badge' }, 'Local Demo')
                    ),
                    h('p', { style: { margin: 0, fontSize: 12, color: 'var(--muted)', lineHeight: 1.4 } },
                        'For local development, enter immediately as the Super Admin to manage tenant access.'
                    ),
                    h('button', {
                        type: 'button',
                        className: 'btn-demo-instant',
                        disabled: demoBusy,
                        onClick: demoLogin
                    }, demoBusy ? 'Entering Super Admin workspace…' : 'Enter as Super Admin →')
                ),

                // Switch Tab Link
                h('button', {
                    type: 'button',
                    className: 'auth-switch',
                    style: { marginTop: 16 },
                    onClick: () => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError(''); }
                }, mode === 'signin' ? 'New user? Create a free account →' : 'Already registered? Sign in →')
            )
        )
    );
}

function UploadForm({ selectedProject, projects = [], isAdmin = false, onStatus, onUploaded }) {
    const [files, setFiles] = useState([]);
    const [busy, setBusy] = useState(false);
    const [projectId, setProjectId] = useState(selectedProject || '');
    const [projectName, setProjectName] = useState(selectedProject || '');
    const inputRef = useRef(null);
    const formRef = useRef(null);

    useEffect(() => {
        if (selectedProject) {
            setProjectId(selectedProject);
            if (!projectName) setProjectName(selectedProject);
        } else if (!isAdmin && projects.length && !projectId) {
            setProjectId(projects[0].project_id);
            setProjectName(projects[0].project_name || projects[0].project_id);
        }
    }, [selectedProject, projects, isAdmin]);

    const chooseFiles = selected => {
        const next = Array.from(selected || []);
        setFiles(next);
    };

    async function submit(event) {
        event.preventDefault();
        if (!files.length) return onStatus('Choose at least one file before submitting.', 'error');
        setBusy(true);
        onStatus(`Uploading ${files.length} file${files.length === 1 ? '' : 's'} and vectorizing them into Qdrant…`);
        try {
            const data = new FormData(formRef.current);
            data.delete('files');
            files.forEach(file => data.append('files', file));
            const response = await apiFetch('/upload/batch', { method: 'POST', body: data });
            const body = await response.json();
            if (!response.ok) throw new Error(body.detail || `Upload failed (${response.status})`);
            onStatus(`✓ ${body.documents.length} document${body.documents.length === 1 ? '' : 's'} indexed for ${body.project_id} · ${body.total_chunks} chunks ready for search.`, 'ok');
            setFiles([]);
            if (inputRef.current) inputRef.current.value = '';
            if (onUploaded) onUploaded();
        } catch (error) {
            onStatus(error.message, 'error');
        } finally {
            setBusy(false);
        }
    }

    return h('form', { ref: formRef, onSubmit: submit },
        h('label', {
            className: 'drop',
            onDragOver: event => event.preventDefault(),
            onDrop: event => { event.preventDefault(); chooseFiles(event.dataTransfer.files); }
        },
            h('input', {
                ref: inputRef,
                name: 'files',
                type: 'file',
                accept: fileTypes,
                multiple: true,
                required: true,
                onChange: event => chooseFiles(event.target.files)
            }),
            h('div', null,
                h('strong', null, 'Drop project files here or click to browse'),
                h('span', null, 'Supports PDF, Word, PowerPoint, Markdown, TXT, and JSON')
            )
        ),
        h('div', { className: 'file-name' },
            files.length ? `${files.length} file${files.length === 1 ? '' : 's'} selected (${files.map(f => f.name).join(', ')})` : 'No files selected'
        ),
        !isAdmin && !projects.length && h('div', { className: 'empty-box', style: { margin: '12px 0' } },
            h('strong', null, 'No project access assigned'),
            h('p', null, 'Ask an organization admin to grant you a project role before uploading documents.')
        ),
        h('div', { className: 'fields' },
            h('label', null, 'Project ID', isAdmin
                ? h('input', {
                    name: 'project_id', value: projectId,
                    onChange: e => setProjectId(e.target.value),
                    placeholder: 'e.g. atlas-web', required: true
                })
                : h('select', {
                    name: 'project_id', value: projectId,
                    onChange: e => {
                        setProjectId(e.target.value);
                        const selected = projects.find(project => project.project_id === e.target.value);
                        if (selected) setProjectName(selected.project_name || selected.project_id);
                    }, required: true, disabled: !projects.length
                }, projects.map(project => h('option', { key: project.project_id, value: project.project_id }, project.project_name || project.project_id)))
            ),
            h('label', null, 'Project Name',
                h('input', {
                    name: 'project_name',
                    value: projectName,
                    onChange: e => setProjectName(e.target.value),
                    placeholder: 'e.g. Atlas Web Portal',
                    required: true, disabled: !isAdmin && !projects.length
                })
            ),
            h('label', null, 'Delivery Stage', h(Select, { name: 'stage', options: stages })),
            h('label', null, 'Document Type', h(Select, { name: 'doc_type', options: documentTypes })),
            h('label', { className: 'wide' }, 'Visible to Teams (optional)',
                h('input', { name: 'visible_to_teams', placeholder: 'e.g. team_eng, team_qa (leave empty for all teams)' })
            ),
            h('label', null, 'Sensitivity Clearance Level',
                h(Select, {
                    name: 'sensitivity_level',
                    options: [
                        { value: '0', label: 'Level 0 - Public' },
                        { value: '1', label: 'Level 1 - Internal' },
                        { value: '2', label: 'Level 2 - Confidential' },
                        { value: '3', label: 'Level 3 - Restricted' }
                    ],
                    defaultValue: '1'
                })
            )
        ),
        h('button', { type: 'submit', disabled: busy || (!isAdmin && !projects.length) }, busy ? 'Ingesting & Vectorizing…' : 'Ingest & Index Documents →')
    );
}

function AskForm({ selectedProject, projects = [], onSelectProject }) {
    const [question, setQuestion] = useState('');
    const [project, setProject] = useState(selectedProject || '');
    const [result, setResult] = useState(null);
    const [busy, setBusy] = useState(false);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        if (selectedProject !== undefined) setProject(selectedProject);
    }, [selectedProject]);

    const samplePrompts = [
        'Summarize the core project goals and architecture',
        'What are the key functional requirements and deliverables?',
        'What security, compliance, and access policies are outlined?',
        'List identified risks, dependencies, and testing strategies',
    ];

    async function executeQuery(queryText, targetProject) {
        setBusy(true);
        setResult(null);
        try {
            const response = await apiFetch('/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: queryText, project_id: targetProject || null })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
            setResult(data);
        } catch (error) {
            setResult({ answer: `⚠️ Error: ${error.message}`, sources: [] });
        } finally {
            setBusy(false);
        }
    }

    function submit(event) {
        if (event) event.preventDefault();
        if (!question.trim()) return;
        executeQuery(question, project);
    }

    function handlePromptClick(prompt) {
        setQuestion(prompt);
        executeQuery(prompt, project);
    }

    function copyAnswer() {
        if (!result || !result.answer) return;
        navigator.clipboard.writeText(result.answer);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    }

    return h('section', { className: 'panel section', id: 'ask' },
        h('div', { className: 'panel-head' },
            h('div', null,
                h('h2', null, 'Ask DocFlow AI — Project Knowledge Q&A'),
                h('p', { style: { margin: '4px 0 0', fontSize: 13, color: 'var(--muted)' } },
                    'Grounded retrieval-augmented question answering across all authorized project documentation.'
                )
            ),
            h('span', { className: 'index' }, '02 / ASK AI')
        ),
        h('form', { onSubmit: submit },
            h('div', { className: 'ask-project-select' },
                h('label', null, 'Scope to Project (Everyone has access across all projects)',
                    h('select', {
                        value: project,
                        onChange: e => {
                            setProject(e.target.value);
                            if (onSelectProject) onSelectProject(e.target.value);
                        }
                    },
                        h('option', { value: '' }, '🌐 All Projects (Cross-project knowledge search)'),
                        projects.map(p => h('option', { key: p.project_id, value: p.project_id },
                            `📁 ${p.project_name || p.project_id} (${p.document_count} doc${p.document_count === 1 ? '' : 's'})`
                        ))
                    )
                ),
                project && h('button', {
                    type: 'button',
                    className: 'btn-secondary',
                    style: { width: 'auto', margin: 0, padding: '10px 14px', fontSize: 12 },
                    onClick: () => {
                        setProject('');
                        if (onSelectProject) onSelectProject('');
                    }
                }, 'Reset to All Projects')
            ),
            h('div', { style: { marginTop: 14 } },
                h('label', null, 'Your Question',
                    h('textarea', {
                        value: question,
                        onChange: event => setQuestion(event.target.value),
                        placeholder: 'Ask any question about requirements, architecture, API specs, decisions, or test plans…',
                        required: true,
                        rows: 3
                    })
                )
            ),
            h('div', { className: 'prompt-pills-label' }, '💡 Suggested questions (click to ask immediately):'),
            h('div', { className: 'prompt-pills' },
                samplePrompts.map((prompt, idx) => h('button', {
                    key: idx,
                    type: 'button',
                    className: 'prompt-pill',
                    onClick: () => handlePromptClick(prompt)
                }, prompt))
            ),
            h('button', { type: 'submit', disabled: busy },
                busy ? 'Retrieving sources and synthesizing answer with Gemini…' : 'Ask Question with Gemini AI →'
            ),
            result && h('div', { style: { marginTop: 24 } },
                h('div', { className: 'answer' },
                    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 } },
                        h('strong', { style: { color: 'var(--mint-dark)', fontSize: 14, textTransform: 'uppercase', letterSpacing: '.05em' } },
                            '🤖 AI Generated Answer'
                        ),
                        h('button', {
                            type: 'button',
                            className: 'btn-secondary',
                            style: { width: 'auto', margin: 0, padding: '4px 10px', fontSize: 11 },
                            onClick: copyAnswer
                        }, copied ? '✓ Copied' : '📋 Copy answer')
                    ),
                    h(FormattedAnswer, { text: result.answer })
                ),
                result.sources && result.sources.length > 0 && h('div', { style: { marginTop: 18 } },
                    h('strong', { style: { fontSize: 13, color: 'var(--navy)', textTransform: 'uppercase', letterSpacing: '.04em' } },
                        `📚 Cited Knowledge Sources (${result.sources.length})`
                    ),
                    h('div', { className: 'source-grid' },
                        result.sources.map((source, index) => h('div', { className: 'source-card', key: index },
                            h('div', { className: 'source-card-header' },
                                h('strong', { style: { fontSize: 12, color: 'var(--navy)' } },
                                    `[Source ${index + 1}] ${source.section_title || 'Document Chunk'}`
                                ),
                                h('span', { className: 'source-score' }, `Score: ${(source.score * 100).toFixed(1)}%`)
                            ),
                            h('div', { className: 'source-snippet' }, source.chunk_text),
                            h('div', { style: { marginTop: 6, fontSize: 10, color: 'var(--muted)', fontFamily: 'DM Mono, monospace' } },
                                `Doc ID: ${source.document_id}`
                            )
                        ))
                    )
                )
            )
        )
    );
}

function DatabaseExplorer({ projects = [], documents = [], onSelectForAsk, onSelectForUpload, onRefresh, busy }) {
    const [searchTerm, setSearchTerm] = useState('');
    const [filterProject, setFilterProject] = useState('');
    const [filterStage, setFilterStage] = useState('');
    const [filterDocType, setFilterDocType] = useState('');
    const [viewMode, setViewMode] = useState('table'); // 'table' or 'projects'
    const [expandedProjectId, setExpandedProjectId] = useState('');

    const totalChunks = documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);

    const filteredDocuments = documents.filter(doc => {
        const matchesSearch = !searchTerm ||
            (doc.filename && doc.filename.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (doc.project_id && doc.project_id.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (doc.project_name && doc.project_name.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (doc.stage && doc.stage.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (doc.doc_type && doc.doc_type.toLowerCase().includes(searchTerm.toLowerCase()));

        const matchesProject = !filterProject || doc.project_id === filterProject;
        const matchesStage = !filterStage || doc.stage === filterStage;
        const matchesDocType = !filterDocType || doc.doc_type === filterDocType;

        return matchesSearch && matchesProject && matchesStage && matchesDocType;
    });

    const filteredProjects = projects.filter(p => {
        return !searchTerm ||
            (p.project_id && p.project_id.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (p.project_name && p.project_name.toLowerCase().includes(searchTerm.toLowerCase()));
    });

    function getFileIcon(filename = '') {
        const ext = filename.split('.').pop().toLowerCase();
        if (ext === 'pdf') return 'PDF';
        if (ext === 'md') return 'MD';
        if (ext === 'json') return '{ }';
        if (ext === 'doc' || ext === 'docx') return 'DOC';
        if (ext === 'ppt' || ext === 'pptx') return 'PPT';
        return 'TXT';
    }

    function openDocument(documentId) {
        openAuthorizedFile(documentId).catch(error => alert(error.message));
    }

    function openSqliteRecord(documentId) {
        openAuthorizedSqliteRecord(documentId).catch(error => alert(error.message));
    }

    return h('section', { className: 'panel section db-explorer', id: 'database' },
        h('div', { className: 'panel-head' },
            h('div', null,
                h('h2', null, '🗄️ Database & Project Repository Explorer'),
                h('p', { style: { margin: '4px 0 0', fontSize: 13, color: 'var(--muted)' } },
                    'All uploaded projects, source documents, and vectorized chunks stored in SQLite & Qdrant.'
                )
            ),
            h('div', { style: { display: 'flex', gap: 8 } },
                h('button', {
                    type: 'button',
                    className: 'btn-secondary',
                    onClick: onRefresh,
                    disabled: busy,
                    style: { width: 'auto', margin: 0, padding: '8px 14px', fontSize: 12 }
                }, busy ? 'Refreshing…' : 'Refresh Database ↻'),
                h('button', {
                    type: 'button',
                    onClick: () => onSelectForUpload(''),
                    style: { width: 'auto', margin: 0, padding: '8px 14px', fontSize: 12 }
                }, '+ Ingest Document')
            )
        ),

        // Database Summary Stats Bar
        h('div', { className: 'metric-grid', style: { margin: '16px 20px' } },
            h('div', { className: 'metric' },
                h('span', { className: 'metric-label' }, 'Total Uploaded Projects'),
                h('strong', { className: 'metric-value' }, projects.length),
                h('span', { className: 'metric-note' }, 'Active Knowledge Spaces')
            ),
            h('div', { className: 'metric' },
                h('span', { className: 'metric-label' }, 'Total Indexed Documents'),
                h('strong', { className: 'metric-value' }, documents.length),
                h('span', { className: 'metric-note' }, 'Search-Ready Files')
            ),
            h('div', { className: 'metric' },
                h('span', { className: 'metric-label' }, 'Vectorized Chunks'),
                h('strong', { className: 'metric-value' }, totalChunks),
                h('span', { className: 'metric-note' }, 'Dense + Sparse Embedded')
            ),
            h('div', { className: 'metric' },
                h('span', { className: 'metric-label' }, 'Database Storage Engine'),
                h('strong', { className: 'metric-value', style: { fontSize: 20, marginTop: 10 } }, 'SQLite + Qdrant'),
                h('span', { className: 'metric-note' }, 'docflow.db & tenant collections')
            )
        ),

        // Search & Filter Toolbar
        h('div', { className: 'db-toolbar' },
            h('div', { className: 'db-filter-group' },
                h('input', {
                    className: 'db-search-input',
                    type: 'text',
                    value: searchTerm,
                    onChange: e => setSearchTerm(e.target.value),
                    placeholder: '🔍 Search projects, filenames, stages, doc types…'
                }),
                h('select', {
                    className: 'db-select',
                    value: filterProject,
                    onChange: e => setFilterProject(e.target.value)
                },
                    h('option', { value: '' }, 'All Projects'),
                    projects.map(p => h('option', { key: p.project_id, value: p.project_id }, p.project_name || p.project_id))
                ),
                h('select', {
                    className: 'db-select',
                    value: filterStage,
                    onChange: e => setFilterStage(e.target.value)
                },
                    h('option', { value: '' }, 'All Stages'),
                    stages.map(s => h('option', { key: s, value: s }, s))
                ),
                h('select', {
                    className: 'db-select',
                    value: filterDocType,
                    onChange: e => setFilterDocType(e.target.value)
                },
                    h('option', { value: '' }, 'All Doc Types'),
                    documentTypes.map(d => h('option', { key: d, value: d }, d))
                ),
                (searchTerm || filterProject || filterStage || filterDocType) && h('button', {
                    type: 'button',
                    className: 'btn-secondary',
                    style: { width: 'auto', margin: 0, padding: '7px 11px', fontSize: 11 },
                    onClick: () => {
                        setSearchTerm('');
                        setFilterProject('');
                        setFilterStage('');
                        setFilterDocType('');
                    }
                }, 'Clear Filters ✕')
            ),
            h('div', { className: 'view-toggle' },
                h('button', {
                    type: 'button',
                    className: viewMode === 'table' ? 'active' : '',
                    onClick: () => setViewMode('table')
                }, '📄 All Documents Table'),
                h('button', {
                    type: 'button',
                    className: viewMode === 'projects' ? 'active' : '',
                    onClick: () => setViewMode('projects')
                }, '🏢 Grouped by Project')
            )
        ),

        // Table View Mode
        viewMode === 'table' && h('div', { className: 'db-table-wrapper' },
            filteredDocuments.length === 0
                ? h('div', { className: 'empty-box' },
                    h('strong', null, 'No documents found in database'),
                    h('p', null, searchTerm ? 'Try adjusting your search criteria.' : 'Upload your first document to populate the database.')
                )
                : h('table', { className: 'db-table' },
                    h('thead', null,
                        h('tr', null,
                            h('th', null, 'Document Name'),
                            h('th', null, 'Project'),
                            h('th', null, 'Delivery Stage'),
                            h('th', null, 'Document Type'),
                            h('th', null, 'Chunks'),
                            h('th', null, 'Sensitivity'),
                            h('th', null, 'Uploaded Date'),
                            h('th', { style: { textAlign: 'right' } }, 'Actions')
                        )
                    ),
                    h('tbody', null,
                        filteredDocuments.map(doc => h('tr', { key: doc.document_id },
                            h('td', null,
                                h('div', { className: 'doc-name' },
                                    h('span', { className: 'doc-icon' }, getFileIcon(doc.filename)),
                                    h('span', null, doc.filename)
                                )
                            ),
                            h('td', null,
                                h('span', { className: 'badge badge-project' }, doc.project_name || doc.project_id)
                            ),
                            h('td', null,
                                h('span', { className: 'badge badge-stage' }, doc.stage)
                            ),
                            h('td', null,
                                h('span', { className: 'badge badge-type' }, doc.doc_type)
                            ),
                            h('td', null,
                                h('span', { className: 'badge badge-chunks' }, `${doc.chunk_count} chunks`)
                            ),
                            h('td', null,
                                h('span', { className: 'pill', style: { fontSize: 10 } }, `Lvl ${doc.sensitivity_level}`)
                            ),
                            h('td', { style: { fontSize: 11, color: 'var(--muted)', fontFamily: 'DM Mono, monospace' } },
                                doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '-'
                            ),
                            h('td', { style: { textAlign: 'right' } },
                                h('button', {
                                    type: 'button',
                                    className: 'btn-action-sm',
                                    onClick: () => openDocument(doc.document_id)
                                }, 'Open File ↗'),
                                h('button', {
                                    type: 'button',
                                    className: 'btn-action-sm',
                                    onClick: () => openSqliteRecord(doc.document_id)
                                }, 'SQLite ↗'),
                                h('button', {
                                    type: 'button',
                                    className: 'btn-action-sm',
                                    onClick: () => onSelectForAsk(doc.project_id)
                                }, '💬 Ask AI')
                            )
                        ))
                    )
                )
        ),

        // Grouped by Project View Mode
        viewMode === 'projects' && h('div', { className: 'project-list', style: { padding: '20px' } },
            filteredProjects.length === 0
                ? h('div', { className: 'empty-box' },
                    h('strong', null, 'No projects found'),
                    h('p', null, 'Upload documents into a project space to see it listed here.')
                )
                : filteredProjects.map(project => {
                    const projectDocs = documents.filter(d => d.project_id === project.project_id);
                    const isExpanded = expandedProjectId === project.project_id;
                    return h('div', { className: 'project-row', key: project.project_id, style: { flexDirection: 'column', alignItems: 'stretch' } },
                        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' } },
                            h('div', { className: 'project-details' },
                                h('button', {
                                    className: 'project-key',
                                    type: 'button',
                                    onClick: () => setExpandedProjectId(isExpanded ? '' : project.project_id)
                                }, `📁 ${project.project_name || project.project_id}`),
                                h('span', null,
                                    `ID: ${project.project_id}  ·  ${projectDocs.length} document${projectDocs.length === 1 ? '' : 's'}  ·  ${projectDocs.reduce((s, d) => s + (d.chunk_count || 0), 0)} chunks`
                                )
                            ),
                            h('div', { style: { display: 'flex', gap: 8 } },
                                h('button', {
                                    type: 'button',
                                    className: 'btn-action-sm',
                                    onClick: () => onSelectForAsk(project.project_id)
                                }, '💬 Ask AI about this Project'),
                                h('button', {
                                    type: 'button',
                                    className: 'btn-secondary',
                                    style: { width: 'auto', margin: 0, padding: '6px 12px', fontSize: 11 },
                                    onClick: () => onSelectForUpload(project.project_id)
                                }, '+ Add Documents')
                            )
                        ),
                        isExpanded && h('div', { className: 'document-list', style: { marginTop: 12 } },
                            projectDocs.length === 0
                                ? h('div', { style: { padding: '8px 0', color: 'var(--muted)', fontSize: 12 } }, 'No documents recorded for this project yet.')
                                : projectDocs.map(doc => h('div', { className: 'document-item', key: doc.document_id },
                                    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                                        h('span', { className: 'doc-icon' }, getFileIcon(doc.filename)),
                                        h('strong', null, doc.filename)
                                    ),
                                    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                                        h('span', { className: 'badge badge-stage' }, doc.stage),
                                        h('span', { className: 'badge badge-type' }, doc.doc_type),
                                        h('span', { className: 'badge badge-chunks' }, `${doc.chunk_count} chunks`),
                                        h('button', {
                                            type: 'button', className: 'btn-action-sm',
                                            style: { padding: '3px 8px', fontSize: 10 },
                                            onClick: () => openAuthorizedFile(doc.document_id).catch(error => alert(error.message))
                                        }, 'Open File'),
                                        h('button', {
                                            type: 'button', className: 'btn-action-sm',
                                            style: { padding: '3px 8px', fontSize: 10 },
                                            onClick: () => openAuthorizedSqliteRecord(doc.document_id).catch(error => alert(error.message))
                                        }, 'SQLite'),
                                        h('button', {
                                            type: 'button',
                                            className: 'btn-action-sm',
                                            style: { padding: '3px 8px', fontSize: 10 },
                                            onClick: () => onSelectForAsk(project.project_id)
                                        }, 'Ask AI')
                                    )
                                ))
                        )
                    );
                })
        )
    );
}

function AuthorizationView({ access, projects = [], documents = [], onRefresh, busy }) {
    const [auditEntries, setAuditEntries] = useState([]);
    const [users, setUsers] = useState([]);
    const [accessEmail, setAccessEmail] = useState('');
    const [projectAccessEmail, setProjectAccessEmail] = useState('');
    const [projectAccessId, setProjectAccessId] = useState('');
    const [projectAccessRole, setProjectAccessRole] = useState('member');
    const isSuperAdmin = access?.is_org_admin === true;
    const canReview = isSuperAdmin || access?.role === 'reviewer' || access?.role === 'admin';
    const title = isSuperAdmin ? 'Super Admin Access Control' : canReview ? 'Reviewer Access View' : 'Team Member Access View';
    const description = isSuperAdmin
        ? 'Organization admin scope: every project in this tenant, with document attributes and tenant isolation enforced.'
        : access?.role === 'reviewer'
            ? 'Reviewer scope: assigned project documents plus pending submissions that you are authorized to approve or reject.'
            : 'Member scope: assigned projects and documents permitted by project, team, clearance, workflow, or uploader ownership.';
    const projectNote = isSuperAdmin ? 'All tenant projects' : 'Assigned projects';
    const documentNote = isSuperAdmin ? 'All tenant documents' : access?.role === 'reviewer' ? 'Authorized review documents' : 'Policy-filtered records';

    useEffect(() => {
        if (!isSuperAdmin) return;
        apiFetch('/admin/audit-log')
            .then(response => response.ok ? response.json() : [])
            .then(setAuditEntries)
            .catch(() => setAuditEntries([]));
        apiFetch('/admin/users')
            .then(response => response.ok ? response.json() : [])
            .then(setUsers)
            .catch(() => setUsers([]));
    }, [isSuperAdmin, documents]);

    async function changeWorkflow(documentId, action, reason) {
        const response = await apiFetch(`/documents/${encodeURIComponent(documentId)}/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: action === 'reject' ? JSON.stringify({ rejection_reason: reason }) : JSON.stringify({ approval_reason: reason || null })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Workflow action failed');
        await onRefresh();
    }

    async function assignRole(userId, projectId, role) {
        const response = await apiFetch(`/admin/users/${encodeURIComponent(userId)}/role?project_id=${encodeURIComponent(projectId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Role assignment failed');
        const refreshed = await apiFetch('/admin/users');
        if (refreshed.ok) setUsers(await refreshed.json());
    }

    async function assignAccess(event) {
        event.preventDefault();
        const response = await apiFetch('/admin/access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: accessEmail,
                role: 'admin'
            })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Access assignment failed');
        setAccessEmail('');
        alert(`Access updated for ${data.email}`);
        const refreshed = await apiFetch('/admin/users');
        if (refreshed.ok) setUsers(await refreshed.json());
    }

    async function assignProjectAccess(event) {
        event.preventDefault();
        const response = await apiFetch('/admin/project-access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: projectAccessEmail, project_id: projectAccessId, role: projectAccessRole })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Project assignment failed');
        setProjectAccessEmail('');
        alert(`${data.email} now has ${data.role} access to ${data.project_id}`);
        const refreshed = await apiFetch('/admin/users');
        if (refreshed.ok) setUsers(await refreshed.json());
    }

    return h('section', { className: 'panel section', id: 'authorization' },
        h('div', { className: 'panel-head' },
            h('div', null,
                h('h2', null, title),
                h('p', { style: { margin: '4px 0 0', fontSize: 13, color: 'var(--muted)' } }, description)
            ),
            h('button', { type: 'button', onClick: onRefresh, disabled: busy }, busy ? 'Refreshing…' : 'Refresh Access ↻')
        ),
        !isSuperAdmin && h('div', { className: 'empty-box', style: { margin: '16px 20px' } },
            h('strong', null, 'Access Control is Super Admin only'),
            h('p', null, 'Your current account can view its authorized access. Sign in with the Super Admin account to grant Admin access by email.')
        ),
        h('div', { className: 'metric-grid', style: { margin: '16px 20px' } },
            h('div', { className: 'metric' }, h('span', { className: 'metric-label' }, 'RBAC Role'), h('strong', { className: 'metric-value' }, access?.role || 'member'), h('span', { className: 'metric-note' }, 'Role-based permissions')),
            h('div', { className: 'metric' }, h('span', { className: 'metric-label' }, 'ABAC Clearance'), h('strong', { className: 'metric-value' }, `Level ${access?.sensitivity_clearance ?? '-'}`), h('span', { className: 'metric-note' }, 'Sensitivity attribute')),
            h('div', { className: 'metric' }, h('span', { className: 'metric-label' }, 'Visible Projects'), h('strong', { className: 'metric-value' }, projects.length), h('span', { className: 'metric-note' }, projectNote)),
            h('div', { className: 'metric' }, h('span', { className: 'metric-label' }, 'Visible Documents'), h('strong', { className: 'metric-value' }, documents.length), h('span', { className: 'metric-note' }, documentNote))
        ),
        h('div', { className: 'project-list', style: { padding: '20px' } },
            projects.map(project => {
                const projectDocuments = documents.filter(document => document.project_id === project.project_id);
                return h('div', { className: 'project-row', key: project.project_id },
                    h('div', { className: 'project-details' },
                        h('strong', null, project.project_name || project.project_id),
                        h('span', null, `${projectDocuments.length} authorized document${projectDocuments.length === 1 ? '' : 's'}`)
                    ),
                    h('div', { className: 'document-list' }, projectDocuments.map(document => h('div', { className: 'document-item', key: document.document_id },
                        h('strong', null, document.filename),
                        h('span', null, `${document.workflow_state || 'draft'} · ${document.uploaded_by === access?.user_id ? 'uploaded by you' : 'project document'}`),
                        h('div', { style: { display: 'flex', gap: 6 } },
                            h('button', { type: 'button', className: 'btn-action-sm', onClick: () => openAuthorizedFile(document.document_id).catch(error => alert(error.message)) }, 'Open File ↗'),
                            h('button', { type: 'button', className: 'btn-action-sm', onClick: () => openAuthorizedSqliteRecord(document.document_id).catch(error => alert(error.message)) }, 'SQLite ↗'),
                            !isSuperAdmin && document.uploaded_by === access?.user_id && ['draft', 'rejected'].includes(document.workflow_state || 'draft') && h('button', {
                                type: 'button', className: 'btn-action-sm',
                                onClick: () => changeWorkflow(document.document_id, 'submit').catch(error => alert(error.message))
                            }, 'Submit for Review'),
                            canReview && document.workflow_state === 'pending_review' && h('button', {
                                type: 'button', className: 'btn-action-sm',
                                onClick: () => changeWorkflow(document.document_id, 'approve', '').catch(error => alert(error.message))
                            }, 'Approve'),
                            canReview && document.workflow_state === 'pending_review' && h('button', {
                                type: 'button', className: 'btn-action-sm',
                                onClick: () => {
                                    const reason = window.prompt('Rejection reason (required):');
                                    if (reason) changeWorkflow(document.document_id, 'reject', reason).catch(error => alert(error.message));
                                }
                            }, 'Reject')
                        )
                    )))
                );
            })
        ),
        isSuperAdmin && h('div', { style: { padding: '0 20px 20px' } },
            h('h3', null, 'Super Admin: Grant Admin Access'),
            h('p', { style: { color: 'var(--muted)', fontSize: 13 } }, 'The super admin can grant only the global Admin role. The recipient will receive access to all projects in this tenant.'),
            h('form', { onSubmit: event => assignAccess(event).catch(error => alert(error.message)), className: 'fields', style: { margin: '0 0 22px' } },
                h('label', null, 'Person Email', h('input', { type: 'email', value: accessEmail, onChange: event => setAccessEmail(event.target.value), placeholder: 'person@company.com', required: true })),
                h('div', { className: 'pill', style: { alignSelf: 'end' } }, 'Admin role only'),
                h('button', { type: 'submit', style: { gridColumn: '1 / -1' } }, 'Grant Admin Access')
            ),
            h('h3', null, 'Assign Project Access by Email'),
            h('p', { style: { color: 'var(--muted)', fontSize: 13 } }, 'Assign one user to as many projects as needed without granting global Admin access.'),
            h('form', { onSubmit: event => assignProjectAccess(event).catch(error => alert(error.message)), className: 'fields', style: { margin: '0 0 22px' } },
                h('label', null, 'Person Email', h('input', { type: 'email', value: projectAccessEmail, onChange: event => setProjectAccessEmail(event.target.value), placeholder: 'person@company.com', required: true })),
                h('label', null, 'Project', h('select', { value: projectAccessId, onChange: event => setProjectAccessId(event.target.value), required: true },
                    h('option', { value: '' }, 'Choose project'), projects.map(project => h('option', { key: project.project_id, value: project.project_id }, project.project_name || project.project_id))
                )),
                h('label', null, 'Project Role', h('select', { value: projectAccessRole, onChange: event => setProjectAccessRole(event.target.value) },
                    h('option', { value: 'member' }, 'Member'), h('option', { value: 'reviewer' }, 'Reviewer'), h('option', { value: 'admin' }, 'Project Admin')
                )),
                h('button', { type: 'submit', style: { alignSelf: 'end' } }, 'Assign Project Access')
            ),
            h('h3', null, 'User & Project Roles'),
            users.length === 0
                ? h('p', { style: { color: 'var(--muted)' } }, 'No tenant users available.')
                : h('div', { className: 'document-list' }, users.map(user => h('div', { className: 'document-item', key: user.user_id },
                    h('strong', null, user.full_name || user.username),
                    h('span', null, `${user.username} · ${user.team_name || 'No team'}${user.is_org_admin ? ' · organization admin' : ''}`),
                    h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
                        projects.map(project => h('select', {
                            key: project.project_id,
                            className: 'db-select',
                            defaultValue: (user.roles || []).find(item => item.project_id === project.project_id)?.role || '',
                            onChange: event => event.target.value && assignRole(user.user_id, project.project_id, event.target.value).catch(error => alert(error.message))
                        },
                            h('option', { value: '' }, project.project_name || project.project_id),
                            h('option', { value: 'member' }, `${project.project_name}: Member`),
                            h('option', { value: 'reviewer' }, `${project.project_name}: Reviewer`),
                            h('option', { value: 'admin' }, `${project.project_name}: Admin`)
                        ))
                    )
                ))),
            h('h3', null, 'Admin Audit Trail'),
            auditEntries.length === 0
                ? h('p', { style: { color: 'var(--muted)' } }, 'No audit events available.')
                : h('div', { className: 'document-list' }, auditEntries.slice(0, 20).map(entry => h('div', { className: 'document-item', key: entry.log_id },
                    h('strong', null, `${entry.action} · ${entry.resource_type}`),
                    h('span', null, `${entry.timestamp} · ${entry.details || 'No details'}`)
                )))
        )
    );
}

function EnterpriseProjects({ onSelect, onSelectForAsk, onRefresh, projects = [], busy }) {
    const [documents, setDocuments] = useState({});
    const [expanded, setExpanded] = useState('');
    const [projectId, setProjectId] = useState('');
    const [projectName, setProjectName] = useState('');
    const [creating, setCreating] = useState(false);

    async function createPersonalProject(event) {
        event.preventDefault();
        setCreating(true);
        try {
            const response = await apiFetch('/projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: projectId, project_name: projectName })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Project creation failed');
            setProjectId('');
            setProjectName('');
            await onRefresh();
        } catch (error) {
            alert(error.message);
        } finally {
            setCreating(false);
        }
    }

    async function toggle(projectId) {
        if (expanded === projectId) return setExpanded('');
        setExpanded(projectId);
        if (documents[projectId]) return;
        const response = await apiFetch(`/projects/${encodeURIComponent(projectId)}/documents`);
        const data = await response.json();
        setDocuments(previous => ({
            ...previous,
            [projectId]: response.ok ? data : { error: data.detail || 'Could not load documents' }
        }));
    }

    return h('section', { className: 'panel section', id: 'projects' },
        h('div', { className: 'toolbar' },
            h('div', null,
                h('h2', null, 'Project Spaces & Portfolio'),
                h('span', { className: 'search-meta' }, 'Active tenant knowledge partitions and indexed collections')
            ),
            h('button', { type: 'button', onClick: onRefresh, disabled: busy }, busy ? 'Refreshing…' : 'Refresh Projects ↻')
        ),
        h('form', { onSubmit: createPersonalProject, className: 'fields', style: { padding: '0 20px 18px' } },
            h('label', null, 'New Personal Project ID', h('input', { value: projectId, onChange: event => setProjectId(event.target.value), placeholder: 'my-project', required: true })),
            h('label', null, 'Project Name', h('input', { value: projectName, onChange: event => setProjectName(event.target.value), placeholder: 'My Project', required: true })),
            h('button', { type: 'submit', disabled: creating, style: { alignSelf: 'end' } }, creating ? 'Creating…' : 'Create Personal Project')
        ),
        h('div', { className: 'project-list' },
            projects.length === 0
                ? h('div', { className: 'empty-box' }, 'No indexed projects yet. Ingest your first project documents.')
                : projects.map(project => {
                    const projectDocuments = documents[project.project_id];
                    return h('div', { className: 'project-row', key: project.project_id },
                        h('div', { className: 'project-details' },
                            h('button', { className: 'project-key', type: 'button', onClick: () => toggle(project.project_id) },
                                project.project_name || project.project_id
                            ),
                            h('span', null, `${project.project_id}  |  ${project.document_count} document${project.document_count === 1 ? '' : 's'}`),
                            expanded === project.project_id && h('div', { className: 'document-list' },
                                !projectDocuments
                                    ? 'Loading documents…'
                                    : projectDocuments.error
                                        ? projectDocuments.error
                                        : projectDocuments.map(document => h('div', { className: 'document-item', key: document.document_id },
                                            h('strong', null, document.filename),
                                            h('span', null, `${document.stage}  |  ${document.doc_type}  |  ${document.chunk_count} chunks`)
                                        ))
                            )
                        ),
                        h('div', { style: { display: 'flex', gap: 8 } },
                            h('button', {
                                type: 'button',
                                className: 'btn-action-sm',
                                onClick: () => onSelectForAsk(project.project_id)
                            }, '💬 Ask AI'),
                            h('button', {
                                type: 'button',
                                onClick: () => onSelect(project.project_id)
                            }, '+ Ingest')
                        )
                    );
                })
        )
    );
}

function PersonalNotes({ projects = [] }) {
    const [notes, setNotes] = useState([]);
    const [title, setTitle] = useState('');
    const [content, setContent] = useState('');
    const [projectId, setProjectId] = useState('');
    const [saving, setSaving] = useState(false);

    async function loadNotes() {
        const response = await apiFetch('/notes');
        if (response.ok) setNotes(await response.json());
    }

    useEffect(() => { loadNotes(); }, []);

    async function saveNote(event) {
        event.preventDefault();
        setSaving(true);
        try {
            const response = await apiFetch('/notes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, content, project_id: projectId || null })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Could not save note');
            setTitle('');
            setContent('');
            setProjectId('');
            setNotes(previous => [data, ...previous]);
        } catch (error) {
            alert(error.message);
        } finally {
            setSaving(false);
        }
    }

    return h('section', { className: 'panel section', id: 'notes' },
        h('div', { className: 'panel-head' },
            h('div', null, h('h2', null, 'Personal Notes'), h('p', { style: { margin: '4px 0 0', fontSize: 13, color: 'var(--muted)' } }, 'Private todos, meeting notes, and follow-up items.')),
            h('button', { type: 'button', onClick: loadNotes }, 'Refresh Notes ↻')
        ),
        h('form', { onSubmit: saveNote, className: 'fields', style: { padding: '0 20px 20px' } },
            h('label', null, 'Title', h('input', { value: title, onChange: event => setTitle(event.target.value), placeholder: 'Meeting follow-up', required: true })),
            h('label', null, 'Project (optional)', h('select', { value: projectId, onChange: event => setProjectId(event.target.value) }, h('option', { value: '' }, 'Personal note'), projects.map(project => h('option', { key: project.project_id, value: project.project_id }, project.project_name || project.project_id)))),
            h('label', { className: 'wide' }, 'Note', h('textarea', { value: content, onChange: event => setContent(event.target.value), placeholder: 'Write a todo, meeting summary, or reminder…', rows: 5, required: true })),
            h('button', { type: 'submit', disabled: saving, style: { gridColumn: '1 / -1' } }, saving ? 'Saving…' : 'Save Personal Note')
        ),
        h('div', { className: 'document-list', style: { padding: '0 20px 20px' } }, notes.length ? notes.map(note => h('article', { className: 'document-item', key: note.note_id }, h('strong', null, note.title), h('span', null, `${note.project_id ? `Project: ${note.project_id}` : 'Personal'} · ${new Date(note.updated_at).toLocaleString()}`), h('p', null, note.content))) : h('p', { style: { color: 'var(--muted)' } }, 'No personal notes yet.'))
    );
}

const tourSteps = [
    {
        target: '#tour-user-profile',
        title: 'User Profile & Security Clearance 👤',
        desc: 'View your active authenticated identity, tenant organization, role (Super Admin, Reviewer, or Member), and ABAC sensitivity clearance level (L1–L3).',
        tip: 'Clearances determine which confidential project documents you can search or view.',
        placement: 'bottom'
    },
    {
        target: '#tour-sidebar-nav',
        title: 'Workspace Navigation 🧭',
        desc: 'Quickly switch between Overview, Ask AI (Q&A), Database Explorer, Document Ingestion, Projects, and Access Control.',
        tip: 'Each space gives you dedicated tools for exploring and managing project documentation.',
        placement: 'right'
    },
    {
        target: '#tour-metrics-grid',
        title: 'Live Repository Metrics 📊',
        desc: 'Real-time overview of your uploaded projects, indexed SQLite documents, vectorized Qdrant chunks, and RBAC search clearance.',
        tip: 'Click on any metric card to jump straight to that section.',
        placement: 'bottom'
    },
    {
        target: '#ask',
        title: 'Ask AI & Grounded Q&A 🤖',
        desc: 'Ask questions in natural language. DocFlow synthesizes accurate answers using Gemini and hybrid dense + sparse retrieval, complete with verifiable citation pill badges [Source N].',
        tip: 'You can scope queries to a single project or search across all authorized spaces.',
        placement: 'bottom'
    },
    {
        target: '#database',
        title: 'Database & File Explorer 🗄️',
        desc: 'Explore all indexed documents, inspect chunk breakdowns, preview original uploaded files directly in your browser, or inspect raw SQLite records.',
        tip: 'Click "Open File" next to any document to view its formatted contents.',
        placement: 'top'
    },
    {
        target: '#upload',
        title: 'Document Ingest & Parser 📄',
        desc: 'Upload PDF, Word (.docx), PowerPoint (.pptx), Markdown, JSON, or Plain Text files. They are automatically chunked, embedded, and indexed into SQLite and Qdrant.',
        tip: 'Supports multi-file batch uploads with automatic sensitivity classification.',
        placement: 'top'
    },
    {
        target: '#tour-tutorial-btn',
        title: 'Tutorial Key & Quick Tour 💡',
        desc: 'You can re-launch this interactive element-by-element tour at any time by pressing the "T" key on your keyboard or clicking this button!',
        tip: 'Shortcuts: [T] = Tour, [Esc] = Close/Skip, [?] = Help.',
        placement: 'right'
    }
];

function ElementTourPopover({ isOpen, initialStep = 0, onClose }) {
    const [step, setStep] = useState(initialStep);
    const [spotlightRect, setSpotlightRect] = useState(null);
    const [popoverStyle, setPopoverStyle] = useState({ top: 0, left: 0, opacity: 0 });

    useEffect(() => {
        setStep(initialStep);
    }, [initialStep, isOpen]);

    useEffect(() => {
        if (!isOpen) {
            setSpotlightRect(null);
            return;
        }

        let cancelled = false;

        const calculatePositions = () => {
            if (cancelled) return;
            const current = tourSteps[step];
            if (!current) return;

            const element = document.querySelector(current.target);
            if (!element) {
                const vWidth = window.innerWidth;
                const vHeight = window.innerHeight;
                setSpotlightRect(null);
                setPopoverStyle({
                    top: Math.max(20, Math.floor(vHeight / 2 - 120)),
                    left: Math.max(20, Math.floor(vWidth / 2 - 190)),
                    width: 380,
                    opacity: 1
                });
                return;
            }

            const rect = element.getBoundingClientRect();
            const padding = 6;

            setSpotlightRect({
                top: Math.max(0, rect.top - padding),
                left: Math.max(0, rect.left - padding),
                width: rect.width + (padding * 2),
                height: rect.height + (padding * 2)
            });

            const popWidth = Math.min(window.innerWidth - 32, 380);
            const popHeight = 320; // generous estimate to keep footer in viewport
            const margin = 14;
            const placement = current.placement || 'bottom';
            let top = 0, left = 0;

            if (placement === 'bottom') {
                top = rect.bottom + margin;
                left = rect.left + (rect.width / 2) - (popWidth / 2);
                if (top + popHeight > window.innerHeight - 16) {
                    top = Math.max(16, rect.top - popHeight - margin);
                }
            } else if (placement === 'top') {
                top = rect.top - popHeight - margin;
                left = rect.left + (rect.width / 2) - (popWidth / 2);
                if (top < 16) top = rect.bottom + margin;
            } else if (placement === 'right') {
                left = rect.right + margin;
                top = rect.top + (rect.height / 2) - (popHeight / 2);
                if (left + popWidth > window.innerWidth - 16) {
                    left = Math.max(16, window.innerWidth - popWidth - 16);
                    top = rect.bottom + margin;
                }
            } else {
                left = Math.max(16, rect.left - popWidth - margin);
                top = rect.top + (rect.height / 2) - (popHeight / 2);
            }

            left = Math.max(16, Math.min(window.innerWidth - popWidth - 16, left));
            top = Math.max(16, Math.min(window.innerHeight - popHeight - 16, top));

            setPopoverStyle({ top: Math.round(top), left: Math.round(left), width: popWidth, opacity: 1 });
        };

        const run = () => {
            if (cancelled) return;
            const current = tourSteps[step];
            if (!current) return;

            const element = document.querySelector(current.target);
            if (element) {
                const rect = element.getBoundingClientRect();
                const isInView = (
                    rect.top >= 0 &&
                    rect.left >= 0 &&
                    rect.bottom <= window.innerHeight &&
                    rect.right <= window.innerWidth
                );
                if (!isInView) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // Wait for smooth scroll to complete before measuring
                    setTimeout(calculatePositions, 500);
                    return;
                }
            }
            calculatePositions();
        };

        const timer = setTimeout(run, 80);
        window.addEventListener('resize', calculatePositions);

        return () => {
            cancelled = true;
            clearTimeout(timer);
            window.removeEventListener('resize', calculatePositions);
        };
    }, [isOpen, step]);

    if (!isOpen) return null;

    const current = tourSteps[step] || tourSteps[0];
    const totalSteps = tourSteps.length;

    const handleNext = () => {
        if (step < totalSteps - 1) {
            setStep(s => s + 1);
        } else {
            onClose();
        }
    };

    const handlePrev = () => {
        if (step > 0) {
            setStep(s => s - 1);
        }
    };

    return h('div', { className: 'tour-overlay-root', onClick: onClose },
        // Spotlight Cutout Box
        spotlightRect && h('div', {
            className: 'tour-spotlight',
            style: {
                top: `${spotlightRect.top}px`,
                left: `${spotlightRect.left}px`,
                width: `${spotlightRect.width}px`,
                height: `${spotlightRect.height}px`
            }
        }),

        // Popover Tooltip Card
        h('div', {
            className: 'tour-popover',
            style: {
                top: `${popoverStyle.top}px`,
                left: `${popoverStyle.left}px`,
                width: popoverStyle.width ? `${popoverStyle.width}px` : undefined,
                opacity: popoverStyle.opacity
            },
            onClick: e => e.stopPropagation()
        },
            // Header
            h('div', { className: 'tour-popover-header' },
                h('span', { className: 'tour-step-badge' }, `Step ${step + 1} of ${totalSteps}`),
                h('button', {
                    type: 'button',
                    className: 'tour-close-btn',
                    onClick: onClose,
                    title: 'Skip / Close Tour (Esc)'
                }, '✕')
            ),

            // Body
            h('div', { className: 'tour-popover-body' },
                h('h3', { className: 'tour-popover-title' }, current.title),
                h('p', { className: 'tour-popover-desc' }, current.desc),
                current.tip && h('div', { className: 'tour-popover-tip' },
                    h('span', null, '💡'),
                    h('span', null, current.tip)
                )
            ),

            // Footer
            h('div', { className: 'tour-popover-footer' },
                h('button', {
                    type: 'button',
                    className: 'tour-btn-skip',
                    onClick: onClose
                }, 'Skip all'),

                h('div', { className: 'tour-dots-indicator' },
                    tourSteps.map((_, i) =>
                        h('span', {
                            key: i,
                            className: `tour-dot-bullet ${i === step ? 'active' : ''}`
                        })
                    )
                ),

                h('div', { className: 'tour-nav-controls' },
                    step > 0 && h('button', {
                        type: 'button',
                        className: 'tour-btn-prev',
                        onClick: handlePrev
                    }, '← Prev'),

                    h('button', {
                        type: 'button',
                        className: 'tour-btn-next',
                        onClick: handleNext
                    }, step < totalSteps - 1 ? 'Next →' : 'Finish ✨')
                )
            )
        )
    );
}

function EnterpriseApp() {
    const [token, setToken] = useState(() => {
        const queryToken = new URLSearchParams(window.location.search).get('auth_token');
        if (queryToken) {
            localStorage.setItem('docflow_token', queryToken);
            window.history.replaceState({}, '', '/');
            return queryToken;
        }
        return localStorage.getItem('docflow_token');
    });

    const [access, setAccess] = useState(null);
    const [projects, setProjects] = useState([]);
    const [allDocuments, setAllDocuments] = useState([]);
    const [selectedProject, setSelectedProject] = useState('');
    const [status, setStatus] = useState({ message: 'Ready to query project knowledge with DocFlow AI.' });
    const [view, setView] = useState('overview');
    const [loadingData, setLoadingData] = useState(false);
    const [showTutorial, setShowTutorial] = useState(false);
    const [tutorialStep, setTutorialStep] = useState(0);

    useEffect(() => {
        const handleLogoutEvent = () => {
            setToken(null);
            setAccess(null);
        };
        window.addEventListener('docflow-logout', handleLogoutEvent);
        return () => window.removeEventListener('docflow-logout', handleLogoutEvent);
    }, []);

    async function loadWorkspaceData() {
        if (!token) return;
        setLoadingData(true);
        try {
            const [projRes, docRes] = await Promise.all([
                apiFetch('/projects'),
                apiFetch('/documents')
            ]);
            if (projRes.ok) {
                const projData = await projRes.json();
                setProjects(projData);
            }
            if (docRes.ok) {
                const docData = await docRes.json();
                setAllDocuments(docData);
            }
        } catch (e) {
            console.error('Failed to load workspace data:', e);
        } finally {
            setLoadingData(false);
        }
    }

    useEffect(() => {
        if (token) {
            loadWorkspaceData();
            apiFetch('/me')
                .then(res => res.ok ? res.json() : null)
                .then(data => {
                    setAccess(data);

                    // Automatically trigger tutorial ONLY for new/1st time user
                    if (data && data.user_id) {
                        const tutorialSeen = localStorage.getItem(`docflow_tutorial_seen_${data.user_id}`);
                        const isNewSignup = localStorage.getItem('docflow_new_signup') === 'true';
                        if (!tutorialSeen && isNewSignup) {
                            setShowTutorial(true);
                            setTutorialStep(0);
                        }
                    }
                })
                .catch(() => setAccess(null));
        } else {
            setAccess(null);
        }
    }, [token]);

    const closeTutorial = () => {
        if (access?.user_id) {
            localStorage.setItem(`docflow_tutorial_seen_${access.user_id}`, 'true');
        }
        localStorage.removeItem('docflow_new_signup');
        setShowTutorial(false);
    };

    const openTutorial = (step = 0) => {
        setView('overview');
        setTutorialStep(step);
        setShowTutorial(true);
    };

    // Keyboard navigation key handler: press 'T' or '?' to toggle interactive tutorial
    useEffect(() => {
        const handleKeyDown = (e) => {
            const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
            if (['input', 'textarea', 'select'].includes(activeTag)) return;
            
            if (e.key === 't' || e.key === 'T' || (e.key === '?' && !e.shiftKey)) {
                e.preventDefault();
                setShowTutorial(prev => {
                    if (!prev) setView('overview');
                    return !prev;
                });
            } else if (e.key === 'Escape') {
                if (showTutorial) {
                    closeTutorial();
                }
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [showTutorial, access]);

    const go = next => {
        setView(next);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const logout = () => {
        localStorage.removeItem('docflow_token');
        setToken(null);
        setAccess(null);
    };

    // If not authenticated, render the dedicated AuthPage as the 1st screen!
    if (!token) {
        return h(AuthPage, {
            onLogin: newToken => {
                setToken(newToken);
            }
        });
    }

    const totalDocuments = allDocuments.length || projects.reduce((sum, p) => sum + (p.document_count || 0), 0);
    const totalChunks = allDocuments.reduce((sum, d) => sum + (d.chunk_count || 0), 0);

    const userInitial = (access?.user_id || 'U')[0].toUpperCase();
    const userDisplay = access?.user_id || 'Active User';

    const accessLabel = access
        ? `${access.tenant_id}  |  ${access.is_org_admin ? 'ORG ADMIN' : 'PROJECT USER'}  |  Clearance Lvl ${access.sensitivity_clearance}`
        : 'Authenticated Session  |  Full Workspace Access';

    const uploadSection = h('section', { className: 'workspace', id: 'upload' },
        h('article', { className: 'panel' },
            h('div', { className: 'panel-head' },
                h('div', null,
                    h('h2', null, 'Ingest Project Documents'),
                    h('p', { style: { margin: '4px 0 0', fontSize: 13, color: 'var(--muted)' } },
                        'Upload PDF, Word, PowerPoint, TXT, Markdown, or JSON to structure, chunk, and index into the database.'
                    )
                ),
                h('span', { className: 'index' }, '01 / INGEST')
            ),
            h(UploadForm, {
                selectedProject,
                projects,
                isAdmin: access?.is_org_admin,
                onStatus: (message, type) => setStatus({ message, type }),
                onUploaded: () => loadWorkspaceData()
            })
        ),
        h('aside', { className: 'side' },
            h(Status, status),
            h('div', { className: 'hint' },
                h('strong', null, 'Governed & Searchable by Design'),
                h('p', null,
                    'Every uploaded document is mapped into SQLite and indexed with dense + sparse vectors in Qdrant for hybrid semantic search.'
                ),
                h('div', { className: 'mono', style: { marginTop: 12 } }, 'POST /upload/batch')
            )
        )
    );

    return h('main', { className: 'enterprise-shell' },
        // Left Sidebar Navigation
        h('aside', { className: 'sidebar' },
            h('div', { className: 'brand' },
                h('span', { className: 'mark' }),
                h('span', null, 'DocFlow AI')
            ),
            h('nav', { id: 'tour-sidebar-nav' },
                h('button', {
                    className: view === 'overview' ? 'active' : '',
                    onClick: () => go('overview')
                }, '01  Overview'),
                h('button', {
                    className: view === 'search' ? 'active' : '',
                    onClick: () => go('search')
                }, '02  Ask AI (Q&A)'),
                h('button', {
                    className: view === 'database' ? 'active' : '',
                    onClick: () => go('database')
                }, '03  Database Explorer'),
                h('button', {
                    className: view === 'upload' ? 'active' : '',
                    onClick: () => go('upload')
                }, '04  Ingest Documents'),
                h('button', {
                    className: view === 'projects' ? 'active' : '',
                    onClick: () => go('projects')
                }, '05  Project Spaces'),
                h('button', {
                    className: view === 'authorization' ? 'active' : '',
                    onClick: () => go('authorization')
                }, '06  Access Control'),
                h('button', {
                    className: view === 'notes' ? 'active' : '',
                    onClick: () => go('notes')
                }, '07  Personal Notes'),
                h('button', {
                    id: 'tour-tutorial-btn',
                    className: `tutorial-nav-btn ${showTutorial ? 'active' : ''}`,
                    onClick: () => openTutorial(0),
                    title: 'Interactive Tutorial Walkthrough (Key: T)'
                },
                    h('span', null, '💡 Interactive Tour'),
                    h('kbd', { className: 'nav-kbd-badge' }, 'T')
                )
            ),
            h('div', { className: 'sidebar-footer' },
                h('strong', null, `👤 ${userDisplay}`),
                h('p', { style: { margin: '4px 0 0', fontSize: 11 } },
                    access?.is_org_admin ? 'Organization admin · all tenant projects.' : 'Team member · authorized project documents only.'
                )
            )
        ),

        // Main Workspace Area
        h('div', { className: 'main-content' },
            // Top Bar
            h('header', { className: 'topbar' },
                h('div', { style: { display: 'flex', alignItems: 'center', gap: 12 } },
                    h('div', { id: 'tour-user-profile', className: 'user-profile-badge' },
                        h('span', { className: 'user-avatar-circle' }, userInitial),
                        h('span', { style: { fontWeight: 600 } }, userDisplay),
                        h('span', { className: 'pill', style: { margin: 0, padding: '2px 7px', fontSize: 10 } }, access?.role || 'member')
                    ),
                    h('span', { className: 'access', style: { display: 'inline-block' } }, accessLabel)
                ),
                h('nav', null,
                    h('button', {
                        type: 'button',
                        className: 'btn-topbar-tutorial',
                        onClick: () => openTutorial(0),
                        title: 'Interactive Tutorial Guide (Press T)'
                    },
                        h('span', { className: 'pulse-dot' }),
                        '💡 Tutorial Tour',
                        h('kbd', { className: 'topbar-kbd' }, 'T')
                    ),
                    access?.is_org_admin && h('button', { type: 'button', onClick: () => go('authorization') }, 'Access Control'),
                    h('a', { href: '/docs', target: '_blank', rel: 'noreferrer' }, 'Swagger Docs ↗'),
                    h('button', { type: 'button', onClick: logout }, 'Sign out')
                )
            ),

            // Page Heading
            h('section', { className: 'page-heading' },
                h('p', { className: 'eyebrow' }, 'Knowledge Base & Retrieval-Augmented Generation'),
                h('h1', null,
                    view === 'database' ? 'Project Database & Document Repository.' :
                        view === 'search' ? 'Ask Questions Across Projects.' :
                            view === 'upload' ? 'Ingest & Structure Project Knowledge.' :
                                view === 'projects' ? 'Project Knowledge Spaces.' :
                                    view === 'authorization' ? (access?.is_org_admin === true ? 'Super Admin Access Control.' : 'My RBAC + ABAC Access.') :
                                        view === 'notes' ? 'Personal Notes & Todos.' :
                                            'Unified Project Knowledge Workspace.'
                ),
                h('p', { className: 'intro' },
                    'DocFlow provides instant retrieval-augmented answers and complete database visibility across all uploaded project documentation.'
                )
            ),

            // Quick Metric Summary Grid
            h('section', { id: 'tour-metrics-grid', className: 'metric-grid' },
                h('div', { className: 'metric', onClick: () => go('database'), style: { cursor: 'pointer' } },
                    h('span', { className: 'metric-label' }, '📁 Uploaded Projects'),
                    h('strong', { className: 'metric-value' }, projects.length),
                    h('span', { className: 'metric-note' }, 'Click to open Database')
                ),
                h('div', { className: 'metric', onClick: () => go('database'), style: { cursor: 'pointer' } },
                    h('span', { className: 'metric-label' }, '📄 Indexed Documents'),
                    h('strong', { className: 'metric-value' }, totalDocuments),
                    h('span', { className: 'metric-note' }, 'In SQLite database')
                ),
                h('div', { className: 'metric', onClick: () => go('search'), style: { cursor: 'pointer' } },
                    h('span', { className: 'metric-label' }, '🧩 Vector Chunks'),
                    h('strong', { className: 'metric-value' }, totalChunks),
                    h('span', { className: 'metric-note' }, 'Qdrant hybrid indexed')
                ),
                h('div', { className: 'metric', onClick: () => go('search'), style: { cursor: 'pointer' } },
                    h('span', { className: 'metric-label' }, '🤖 Ask Q Access'),
                    h('strong', { className: 'metric-value', style: { color: 'var(--mint-dark)' } }, 'Authorized'),
                    h('span', { className: 'metric-note' }, 'RBAC + ABAC search scope')
                )
            ),

            // Main Views
            view === 'overview' && h('div', null,
                h(AskForm, {
                    selectedProject,
                    projects,
                    onSelectProject: proj => setSelectedProject(proj)
                }),
                h(DatabaseExplorer, {
                    projects,
                    documents: allDocuments,
                    busy: loadingData,
                    onRefresh: loadWorkspaceData,
                    onSelectForAsk: proj => {
                        setSelectedProject(proj);
                        go('search');
                    },
                    onSelectForUpload: proj => {
                        setSelectedProject(proj);
                        go('upload');
                    }
                }),
                uploadSection
            ),

            view === 'search' && h(AskForm, {
                selectedProject,
                projects,
                onSelectProject: proj => setSelectedProject(proj)
            }),

            view === 'database' && h(DatabaseExplorer, {
                projects,
                documents: allDocuments,
                busy: loadingData,
                onRefresh: loadWorkspaceData,
                onSelectForAsk: proj => {
                    setSelectedProject(proj);
                    go('search');
                },
                onSelectForUpload: proj => {
                    setSelectedProject(proj);
                    go('upload');
                }
            }),

            view === 'upload' && uploadSection,

            view === 'projects' && h(EnterpriseProjects, {
                projects,
                busy: loadingData,
                onRefresh: loadWorkspaceData,
                onSelect: proj => {
                    setSelectedProject(proj);
                    go('upload');
                },
                onSelectForAsk: proj => {
                    setSelectedProject(proj);
                    go('search');
                }
            }),

            view === 'authorization' && h(AuthorizationView, {
                access,
                projects,
                documents: allDocuments,
                busy: loadingData,
                onRefresh: loadWorkspaceData
            }),

            view === 'notes' && h(PersonalNotes, { projects })
        ),

        // Element-by-Element Spotlight Popover Tour
        h(ElementTourPopover, {
            isOpen: showTutorial,
            initialStep: tutorialStep,
            onClose: closeTutorial
        })
    );
}

ReactDOM.createRoot(document.getElementById('root')).render(h(EnterpriseApp));
