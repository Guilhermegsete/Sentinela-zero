# SENTINELA ZERO

Piloto público de monitoramento solar e noticiário por fontes abertas, com orçamento de hospedagem R$ 0.

- Dashboard estático em `docs/index.html`.
- Coletor Python em `scripts/collect.py`.
- Atualização agendada em `.github/workflows/update.yml`.
- Fonte solar: NOAA SWPC; notícias: BBC World e Al Jazeera.

## Publicação

Em **Settings → Pages**, selecionar **Deploy from a branch**, branch **main**, pasta **/docs**. O primeiro `docs/data.json` é produzido pela execução manual de **Actions → SENTINELA collect → Run workflow**.

## Limites

Coleta agendada não é monitoramento contínuo; GitHub pode atrasar ou suspender agendamentos. Dados NOAA podem mudar de esquema. O painel exibe frescor e falhas e não serve como alerta de segurança crítico. Dados publicados são públicos. Sem segredos/API keys.
