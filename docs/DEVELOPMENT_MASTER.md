# OpenTrace BIM — Registro mestre de desenvolvimento

**Referência:** 2026-10-09 · **Repositório:** `lelopes05/opentrace-bim` · **Release preservado:** 0.12.9

> Abrir a próxima conversa lendo este arquivo na branch/PR de desenvolvimento mais recente. Validar commits/arquivos reais antes de declarar algo integrado. Atualizar este registro ao fechar cada bloco.

## Regras permanentes

- Responder às perguntas do usuário ANTES de programar. Ele valida comportamento e interface; revisão de arquitetura e código é responsabilidade técnica do assistente.
- Trabalhar em blocos e avançar com frentes independentes enquanto o usuário testa outras. Evitar alterações simultâneas ao mesmo arquivo; reconciliar antes de juntar.
- Não empacotar, instalar, mesclar na `main`, publicar release ou atualizar catálogo sem autorização. Branch de desenvolvimento + PR rascunho permitidos.
- Distinguir testes Python de execução do plugin dentro do IngeTrazo. Não alegar teste de runtime não executado.
- Patches de conversas anteriores NÃO equivalem a commits no GitHub. Conferir arquivos e reaplicar conforme necessário.

## Contratos e limites entre motores

- Geometria única paramétrica: `model.py` (parede), `slab_model.py` (laje), `column_model.py`, `beam_model.py`; metadados IFC em `bim.py`, camadas em `layers.py`.
- `levels.py` lê dados da extensão Niveles sem tomar posse do namespace. Reutilizar cenas, cortes, escala e Compositor do IngeTrazo, com APIs privadas centralizadas no adaptador `host.py` quando necessário.
- `architecture_contracts.py` é apenas um contrato JSON-safe de vistas, aberturas e hachuras; não executa ações e não deve alterar o comportamento da 0.12.9.
- Uma vista salva contém câmera, corte, nível, escala de representação e tipo de representação. Nunca duplicar a geometria do modelo.
- A escala 1:50 rege símbolos, hachuras e tamanho gráfico das cotas; NÃO trava o zoom nem promete escala física do monitor.
- 3D livre, inclusive com seção temporária: representação `simple`, sem trama. Planta, corte e elevação documentados: `architectural`. Isométrica cortada pode optar pelo modo arquitetônico.
- Criar cenas/cortes por comandos undoáveis; não modificar `scene.saved_views` ou `scene.section_planes` diretamente sem história (IngeTrazo issue #310).
- Abertura é geometria do hospedeiro; porta/janela é objeto de preenchimento separado e associado por `source_id`. Aberturas livres não exigem elemento de preenchimento.
- Parede deve aceitar abertura livre poligonal (vértices/arestas) em coordenadas locais (distância ao longo do caminho, altura), inclusive curva; retângulos legados mantêm `position,width,sill,height`.
- Permitir `sill=0` nas portas; **não apagar parede baixa** quando porta nominal for mais alta. Recriar malha sem arestas fantasmas. Preservar GUID e abertura/objeto após edição e salvar/reabrir.
- Mínimo: uma porta de abrir e uma janela paramétricas. Porta: três pontos de ancoragem (esquerda/centro/direita), botão único para inverter giro, hotspots/paleta radial; altura só no hotspot superior, posição só nos inferiores, largura em todos.
- Ferragens, puxadores, dobradiças e armaduras complexas são futuros plugins conectáveis; terreno avançado adiado.
- Tramas são vetoriais, editáveis e paramétricas, associadas a materiais/camadas, escalas `paper` (mm de folha) e `model` (m reais); cache por geometria/corte/material/escala, e só renderizam em vistas arquitetônicas.
- Paleta lateral conserva edição. Nova barra contextual é só para criação. Informações do Projeto têm botão próprio mas usam o cadastro BIM existente, acrescido de cliente/localização.
- Manual `?` contextual começa com `O que há de novo` em cada release. Sobre inclui GitHub, discussão IngeTrazo #449 e atualizador oficial; nenhum site fictício.
- Alinhamento/distribuição X/Y/Z em paleta ancorável, com limites reais de grupos e histórico undoável do host.

## Blocos — estado

| Bloco | Escopo | Estado na abertura desta frente |
|---|---|---|
| 00 | Fundação, contratos e testes | Preparado em branch; testes Python necessários |
| 01 | UI, barra de criação, cadastro Projeto, manual, Sobre/novidades | **Parcial:** Informações do Projeto em página própria + Cliente/Localização na branch `dev/project-info-ui-2026-10-09`; demais patches não integrados; UI sem teste no IngeTrazo |
| 02 | Alinhar/distribuir X/Y/Z | Patch anterior, ainda não integrado à `main` |
| 03 | Cenas, plantas por pavimento, vistas/cortes | Barra de vistas em patch; cenas automáticas pendentes |
| 04 | Escalas, cotas e símbolos 2D na viewport | Especificado, não implementado |
| 05A | Aberturas livres e hospedadas sem arestas residuais | Prioritário; gerador da parede ainda limitado |
| 05B | Porta de giro e janela paramétricas | Prioritário, depende de 05A |
| 06 | Tramas vetoriais por material/camada | Contrato preparado; renderizador/editor pendentes |
| 07 | Compositor, IFC, round-trip e testes de regressão | Consolidação pendente |

**Trabalho paralelo:** 01 e 02 separados; 03 e 05A podem progredir em arquivos distintos. 04 depende de 03; 05B de 05A; 06 de 03 e materiais; 07 é integração contínua. Nunca alterar os mesmos arquivos em duas frentes sem reconciliar.

## Achados concretos da versão 0.12.9

- `model.py::normalize_wall_openings()` aceita apenas retângulos internos com margem em cima e embaixo, e impede portas no piso. Precisamos substituir esse limite e resolver as arestas que sobram.
- `openings.py::host_capabilities()` declara `embedded_polygon=False` em paredes. Não declarar suporte antecipadamente sem gerador funcional.
- `slab_opening.py` / `slab_opening_edit.py` já têm o padrão de UX para polígonos. Não transplantar sem adaptar a geometria local da parede.
- `bim.py` já salva projeto/terreno/edifício/autor/organização. Cliente e localização devem entrar no mesmo registro, sem dados duplicados.
- `levels.py` consulta Niveles; proposta de plantas por nível foi registrada no issue #310 do IngeTrazo, mas o código público de Niveles consultado ainda não possuía geração automática.
- IngeTrazo já tem cenas com cortes, Compositor com escala real e uma hachura vetorial 45°; falta biblioteca de material por escala na viewport.
- Arquivo local de conversas anteriores: `opentrace_ui_pending_cumulative.patch` contém barra de vistas, manual/Sobre e alinhamento, mas só valerá como implementado após integração e teste.

## Execução e handoff

1. Bloco 00: validar `architecture_contracts.py` e `tests/test_architecture_contracts.py` com `python -m unittest discover -s tests -v` desde a raiz. Sem hooks novos no `setup()`.
2. Bloco 01: reconciliar patches UI anteriores com branch atual. Priorizar UI limpa, cadastro de projeto e manual.
3. Bloco 02: validar alinhamento pelo bounding box real, Undo/Redo, objetos aninhados, salvar/reabrir.
4. Bloco 05A pode iniciar em paralelo: porta no piso, abertura poligonal livre, parede curva, malha limpa e parede baixa preservada; depois 05B portas/janelas.
5. Blocos 03–04: corte real por pavimento, escalas de representação e vinculação ao Compositor; 06 tramas vetoriais; 07 consolidação e IFC.
6. Testes no IngeTrazo pelo usuário quando necessários: criação/edição, Undo/Redo, salvar/reabrir `.igz`, superfícies vazadas limpas, arquivo IFC Bonsai/Archicad/FreeCAD quando houver ambiente.
7. Antes de terminar cada conversa, registrar status **verificado**, arquivos, testes, branch/commit, questões pendentes e próxima ação neste documento.

**Prompt de retomada:** Leia `docs/DEVELOPMENT_MASTER.md` na branch de desenvolvimento atual de `lelopes05/opentrace-bim`; confira GitHub e os testes antes de continuar. Não publique/empacote sem autorização. Desenvolva primeiro 01 e 02 e em paralelo 05A, mantendo este registro atualizado.

## Última atualização — 2026-10-09

- **Bloco 00:** branch `dev/architecture-foundation-2026-10-09`, PR rascunho #3: contratos de dados e 10 testes Python preparados; sem hooks de runtime.
- **Bloco 01 parcial:** branch `dev/project-info-ui-2026-10-09` baseada no bloco 00. `bim_ui.py`: retirou campos de projeto da página BIM e apresentou painel próprio; `suite_panel.py`: botão `ⓘ` para abrir página de Projeto sem iniciar criação; `bim.py`: incluiu cliente/localização no cadastro e manteve compatibilidade com arquivos antigos. Testes de registro pure-Python foram adicionados.
- **Não concluído:** teste visual no host, demais ajustes de BIM avançado/Help/Sobre, barra contextual, verificação do patch acumulado. PR/branch de desenvolvimento, não release.
- **Próxima frente:** 05A, aberturas livres de parede, vãos com base=0, malha limpa, preparação para porta/janela. Avançar em arquivos isolados, sem modificar a branch principal.
