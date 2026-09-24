# Perfil musical

Este archivo describe nuestros gustos musicales para que el clasificador valore conciertos, festivales y eventos según nuestra afinidad musical.

El objetivo no es limitarse a los artistas mencionados. Debe utilizar estos artistas y estilos como referencias para descubrir otros similares.

## Qué me interesa

* **Géneros:** rock, pop-rock, rock alternativo, rock español, rock internacional, hard rock, heavy metal clásico, punk-rock, indie-rock, indie-pop, electrónica, synth-pop y pop.
* **Épocas:** especial interés por la música de los años 80, 90 y 2000, sin excluir música actual.
* **Música actual:** nos interesa descubrir artistas y grupos actuales que tengan afinidad con estos estilos.
* **Grandes divas del pop:** sí.
* **Cantautores:** sí cuando encajan con nuestros gustos de pop/rock.
* **Festivales:** sí.
* **Tributos:** sí. Un buen tributo a un artista que nos gusta puede considerarse interesante.
* **Salas pequeñas:** sí. La fama o el tamaño del artista no son importantes si existe afinidad musical.
* **Ámbito geográfico:** Galicia. No recomendar desplazamientos fuera de Galicia por defecto.

### Artistas de referencia — afinidad muy alta

Todos estos artistas sirven como señales fuertes de `INTERESTED`:

* Fito & Fitipaldis
* Maroon 5
* Queen
* U2
* Coldplay
* Bon Jovi
* The Killers
* Dire Straits / Mark Knopfler
* Bruce Springsteen
* Guns N' Roses
* AC/DC
* Metallica
* Hombres G
* Manolo García / El Último de la Fila
* M-Clan
* Amaral
* Estopa
* Dani Martín / El Canto del Loco
* Leiva / Pereza
* Arde Bogotá
* Depeche Mode
* Madonna
* Lady Gaga

### También nos gustan

#### Rock, pop-rock y alternativo internacional

* Bryan Adams
* The Rolling Stones
* Aerosmith
* R.E.M.
* Oasis
* Red Hot Chili Peppers
* Foo Fighters
* Green Day
* Linkin Park
* The Offspring
* Blink-182
* Arctic Monkeys
* Muse
* Franz Ferdinand
* Placebo
* Kings of Leon
* Snow Patrol
* Keane
* The Strokes
* Kaiser Chiefs
* Nickelback
* Iron Maiden

#### Pop, rock y new wave de los 80 y 90

* Simple Minds
* INXS
* Tears for Fears
* A-ha
* Duran Duran
* Pet Shop Boys
* Roxette
* The Cranberries
* Texas
* Phil Collins / Genesis
* Sting / The Police
* Eurythmics
* Europe

#### Música española

* Los Secretos
* Duncan Dhu / Mikel Erentxun
* Celtas Cortos
* Jarabe de Palo
* Seguridad Social
* Revólver
* Cómplices
* Elefantes
* Café Quijano
* La Guardia
* Joaquín Sabina
* Miguel Ríos
* Loquillo
* Antonio Orozco
* Pignoise
* Sidecars
* Siloé
* Extremoduro / Robe
* Ska-P
* La Raíz
* Vetusta Morla
* Love of Lesbian
* Izal
* Melendi
* La Oreja de Van Gogh
* Mecano
* Nacha Pop
* Radio Futura
* Alaska
* Tequila
* Los Rodríguez
* La Frontera
* Tam Tam Go!
* OBK

#### Divas y grandes voces del pop

* Madonna
* Lady Gaga
* Cher
* Kylie Minogue
* Pink
* Beyoncé
* Shakira
* Anastacia
* Tina Turner

Las listas anteriores son referencias, **no listas cerradas**.

## Qué suelo evitar

* **Géneros o estilos:** reguetón, trap/urbano, bachata, salsa, flamenco tradicional, rap/hip-hop, techno de club, EDM de macrofestival, jazz, blues, country, metal extremo y hardcore muy duro.
* **Folk gallego:** no.
* **Verbenas y orquestas gallegas:** no.
* No recomendar un evento simplemente porque sea popular, famoso o tenga mucha asistencia.
* La fama del artista no debe aumentar artificialmente su puntuación.

## Matices

* **Si dudas entre interesado y quizá, prefiere:** `INTERESTED` cuando exista una similitud musical razonablemente clara con nuestros artistas y estilos favoritos.
* Utilizar `MAYBE` cuando haya alguna afinidad, pero no sea suficientemente clara.
* Utilizar `IGNORE` cuando el estilo esté claramente alejado de nuestras preferencias.
* Queremos **descubrir música nueva**, por lo que un artista desconocido puede recibir `INTERESTED`.
* No exigir que un artista aparezca explícitamente en este archivo.
* Buscar similitud de género, sonido, época, influencias y público con nuestros artistas de referencia.
* Dar especial peso al rock y pop-rock de los años 80, 90 y 2000 y a artistas actuales que continúen esa línea.
* También somos receptivos al rock más potente, hard rock, heavy clásico, punk-rock, indie y electrónica compatible con estos gustos.
* Un grupo pequeño o desconocido puede ser tan interesante como uno famoso.
* **Valorar únicamente la afinidad musical**, no la fama, precio de la entrada o tamaño del recinto.

### Conciertos y festivales

* Nos interesan conciertos en salas pequeñas, auditorios, pabellones, estadios y al aire libre.
* Nos interesan festivales.
* Un festival puede ser `INTERESTED` aunque solo conozcamos algunos artistas si varios encajan con nuestro perfil.
* No penalizar un festival por incluir artistas que no conocemos.
* Los conciertos de grupos de los 80 y 90 siguen siendo interesantes aunque actualmente tengan menos popularidad.
* Las giras de aniversario y repertorios de grandes éxitos son especialmente interesantes cuando corresponden a artistas afines.

### Tributos

Los tributos **sí nos interesan**.

Un buen tributo a un artista muy afín puede clasificarse como `INTERESTED`.

Ejemplos claros:

* Queen
* U2
* Dire Straits
* AC/DC
* Bon Jovi
* Guns N' Roses
* Hombres G
* Mecano
* ABBA
* y otros artistas compatibles con este perfil.

No asumir que `tributo = IGNORE`.

## Regla general para el clasificador

La pregunta principal debe ser:

> **¿Es probable que musicalmente disfrutemos de este concierto?**

No:

> ¿Es famoso el artista?

Un artista desconocido que suene muy cercano a Fito & Fitipaldis, The Killers, Arde Bogotá, M-Clan, U2, Maroon 5, Muse, Leiva, Bon Jovi o cualquiera de nuestras referencias puede clasificarse directamente como `INTERESTED`.

Por el contrario, un artista extremadamente famoso cuyo estilo esté claramente dentro de los géneros que evitamos debe ser `IGNORE`.

Cuando las señales sean contradictorias o no haya información musical suficiente, utilizar `MAYBE`.
