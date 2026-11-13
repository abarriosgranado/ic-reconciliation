# IC Reconciliation

Aplicación local de conciliación intercompany con Python y SQLite.

## Ejecutar

Requiere Python 3.9 o superior. No necesita dependencias externas.

```sh
python3 app.py --demo
```

Abre http://127.0.0.1:8766. Se genera una base de datos independiente con cuatro empresas ficticias, EUR/GBP/USD y dos cierres mensuales. Octubre incluye 52 registros, 24 grupos, 20 conciliados y cuatro excepciones. Las diferencias se calculan con el motor de conciliación.

Para trabajar con datos propios: `python3 app.py`, en http://127.0.0.1:8765. La aplicación escucha únicamente en el equipo local. Este repositorio no publica un servicio web ni incluye bases de datos personales.

## Funciones

- Dashboard: estado de conciliación y excepciones pendientes.
- Imports: importación CSV por empresa y mapeo; ejecución de conciliaciones.
- Exceptions: comparación en una tabla con colores por empresa, diferencias por referencia y totales.
- History: ejecuciones guardadas y exportación CSV/JSON.
- Mappings: seis mapeos de columnas, NetSuite/Odoo/A3 × Balance/P&L.
- Settings: empresas, monedas, tolerancia y métodos Closing/Average/Historical independientes para Balance, P&L y Patrimonio.

Los métodos se desactivan con One Currency. Las importaciones CSV requieren importes con punto decimal y cuentas ya normalizadas. La columna opcional `category` distingue Patrimonio dentro de Balance; sin ella se utiliza el estado de la importación. Los tipos de cambio son proporcionados por el usuario, en unidades de moneda base por moneda de origen.

## Pruebas

```sh
python3 -m unittest -v
```

## Alcance actual

Las empresas, movimientos y tipos de cambio incluidos son ficticios. No hay conexiones directas a ERPs. La incorporación del maestro Netsuite Chart of Accounts y los mapeos de cuentas está pendiente; los mapeos actuales son de columnas. No se importa Excel ni se conservan originales o versiones anteriores de mapeos. Esta versión local no incorpora autenticación y no debe exponerse directamente a Internet. Para una versión pública interactiva hay que preparar un despliegue específico.
