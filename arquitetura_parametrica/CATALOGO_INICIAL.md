# Biblioteca inicial — Parametric Architecture 0.11

A biblioteca desta versão foi pensada como ponto de partida editável, não como especificação construtiva obrigatória.

## Composições

- 10 presets de paredes: genérica, alvenaria cerâmica, bloco de concreto, opções revestidas e drywall.
- 9 presets de lajes: concreto aparente, pisos, área molhada, coberturas e cobertura verde.
- 20 presets de vigas: concreto, madeira e atalhos para perfis metálicos.
- 10 presets de pilares: concreto, madeira e perfis metálicos.

Todos podem ser aplicados e depois alterados. Presets pessoais são armazenados no perfil do usuário e também podem ser exportados em `.apreset`.

## Perfis Complexos

O catálogo inclui 88 perfis prontos em pastas:

- Estruturais / Aço / Gerdau W — 49 perfis
- Estruturais / Aço / IPE — 11 perfis
- Estruturais / Aço / HEA — 11 perfis
- Estruturais / Aço / HEB — 11 perfis
- Arquitetônicos — 6 perfis iniciais (rodapé, faixa/moldura, corrimão e parede)

Os perfis metálicos usam a geometria nominal de alma/abas, sem os raios de concordância do laminado. Isso mantém o modelo leve e adequado a representação BIM, mas não substitui catálogo estrutural ou cálculo.

## Organização e portabilidade

Perfis pessoais aceitam caminhos de pasta livres, por exemplo:

`Meus Perfis / Rodapés`

`Meu Escritório / Corrimãos`

`Fabricante X / Fachada`

Perfis de catálogo são somente leitura. O comando **Personalizar** duplica o perfil escolhido para `Meus Perfis`, preservando o original.
