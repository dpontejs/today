# Fontes de vagas — pesquisa (2026-11-23)

Objetivo: coletar vagas de ML / DL / Visão Computacional / Agentic AI / MLOps (remoto de preferência) para pré-análise com LLM. Candidatura sempre manual.

Legenda: **V** = testado com requisição real em 2026-11-23; **I** = inferido.

## Decisão

- Fontes principais: APIs públicas de ATS (sem login, sem risco) + busca da Gupy + agregadores remotos.
- LinkedIn só como complemento: endpoint guest sem login, baixo volume, e e-mails de alerta via Gmail.
- **Nunca** automatizar conta logada do LinkedIn (nem secundária).

## Empresas → ATS → endpoint

| Empresa | ATS | Endpoint | Verif. | Notas |
|---|---|---|---|---|
| iFood | Greenhouse | `boards-api.greenhouse.io/v1/boards/ifoodcarreiras/jobs?content=true` | V | token não é `ifood` |
| Nubank | Ashby | `api.ashbyhq.com/posting-api/job-board/nubank` | V | `isRemote`, `workplaceType`, `descriptionPlain` |
| Itaú | Gupy | `vemproitau.gupy.io` (`__NEXT_DATA__`) | V | |
| Mercado Livre | Eightfold | `mercadolibre.eightfold.ai/api/pcsx/search?domain=mercadolibre.com&query=...&location=Brazil&start=0` | V | detalhe: `/api/pcsx/position_details?position_id=..&domain=mercadolibre.com` |
| PicPay | Oracle Recruiting | `epdm.fa.la1.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber=CX_1,keyword=dados,limit=25` | V | `WorkplaceType` |
| Stone | Greenhouse | `boards/stone` | V | majoritariamente comercial |
| XP Inc | Greenhouse | `boards/xpinc` | V | |
| Banco Inter | Greenhouse | `boards/inter` | V | |
| C6 Bank | Greenhouse | `boards/c6bank` | V | site dá 403, API ok |
| QuintoAndar | Greenhouse | `boards/quintoandar` | V | |
| Hotmart | Greenhouse | `boards/hotmartcareersbr` | V | |
| CI&T | Lever | `api.lever.co/v0/postings/ciandt?mode=json` | V | `workplaceType` |
| BTG Pactual | Greenhouse | `boards/btgpactual` | V | |
| VTEX | Greenhouse | `boards/vtex` | V | |
| Creditas | Gupy | `creditas.gupy.io` | V | |
| Wildlife | Greenhouse | `boards/wildlifestudios` | V | |
| Magalu | 99jobs | `99jobs.com/magazine-luiza` | I | só HTML |
| Uber | próprio | — | não | bloqueia curl; usar LinkedIn |

## Endpoints genéricos

- **Gupy portal (V):** `GET https://portal.gupy.io/api/job-search/jobs?jobName=<termo>&workplaceType=remote&limit=&offset=` — `description` completa, `workplaceType`, `careerPageName`, `jobUrl`, `publishedDate`. Possível teto de 100 resultados por busca. (`portal.api.gupy.io/api/v1/jobs` deu 404.)
- **Gupy por empresa (V):** `https://<sub>.gupy.io/` → `<script id="__NEXT_DATA__">` → `props.pageProps.jobs`.
- **Greenhouse (V):** `boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true` — sem campo de remoto; inferir por local/título.
- **Lever (V):** `api.lever.co/v0/postings/<co>?mode=json` — `workplaceType`, `descriptionPlain`.
- **Ashby (V):** `api.ashbyhq.com/posting-api/job-board/<org>?includeCompensation=true`.
- **Workday (V):** `POST https://<t>.wdN.myworkdayjobs.com/wday/cxs/<t>/<site>/jobs` com `{"appliedFacets":{},"limit":20,"offset":0,"searchText":"..."}`.
- **SmartRecruiters (V):** `api.smartrecruiters.com/v1/companies/<id>/postings`.

## Agregadores

- **Himalayas (V):** `himalayas.app/jobs/api/search?q=...&country=Brazil` (20/página).
- **Remotar (V):** `api.remotar.com.br/jobs?search=machine%20learning` (50/página, busca ampla).
- **RemoteOK (V):** `remoteok.com/api` — exige link de volta.

## LinkedIn

- **Guest sem login (V):** `GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...&location=Brazil&f_TPR=r86400&start=0` → fragmento HTML, 10 vagas/página (id, título, empresa, cidade, data). Descrição em `/jobs/view/{id}`. `f_WT` (remoto) é **ignorado** sem login — filtrar pelo texto. Abordagem do [JobSpy](https://github.com/speedyapply/JobSpy/blob/main/jobspy/linkedin/__init__.py) (3–7 s entre páginas; 429/authwall em excesso).
- **Conta logada:** User Agreement 8.2 proíbe bots/scraping; 2.1 permite uma conta, nome real. AIHawk teve contribuidores banidos ([#1084](https://github.com/feder-cr/Jobs_Applier_AI_Agent/issues/1084)); conta de teste restrita em <12 h ([#160](https://github.com/feder-cr/Jobs_Applier_AI_Agent/issues/160)).
- **API oficial:** só publicação, parceiros, sem novas parcerias.
- **E-mails de alerta (I):** sem risco; título/empresa/link, descrição via página guest.
