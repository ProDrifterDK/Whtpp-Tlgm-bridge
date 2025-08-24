

# **Plan Técnico: Desarrollo de un Puente de Mensajería Bidireccional entre WhatsApp y Telegram**

## **Resumen Ejecutivo**

Este documento detalla la arquitectura y la hoja de ruta para el desarrollo de un sistema de software personalizado diseñado para enrutar mensajes de dos cuentas de WhatsApp a una única cuenta de Telegram. El sistema permitirá la comunicación bidireccional, reenviando los mensajes de WhatsApp a Telegram y permitiendo que las respuestas desde Telegram se envíen de vuelta al chat de WhatsApp correspondiente.

Dada la ausencia de una API pública para cuentas personales de WhatsApp, la solución se basará en la automatización de la interfaz de usuario de WhatsApp Web.1 Para lograr un rendimiento eficiente y concurrente, la arquitectura se centrará en el framework

asyncio de Python. La interacción con el navegador se realizará directamente a través de bibliotecas de automatización robustas como Selenium o Playwright, proporcionando un control granular sobre el proceso.

## **Sección 1: Arquitectura General del Sistema**

El núcleo de la aplicación se construirá sobre el framework asyncio de Python para gestionar de manera eficiente y no bloqueante las múltiples operaciones de red y de E/S. La arquitectura se compondrá de tres tareas concurrentes principales:

1. **Tarea Oyente de WhatsApp \#1:** Una instancia de navegador automatizada dedicada a monitorear la primera cuenta de WhatsApp.  
2. **Tarea Oyente de WhatsApp \#2:** Una segunda instancia de navegador automatizada, completamente independiente, para monitorear la segunda cuenta de WhatsApp.  
3. **Tarea del Bot de Telegram:** Un cliente de bot de Telegram que gestiona la comunicación con la API de Telegram, presentando los mensajes al usuario y recibiendo sus respuestas.

La comunicación entre las tareas de los oyentes de WhatsApp y la tarea del bot de Telegram se gestionará a través de una cola asíncrona (asyncio.Queue). Este patrón de diseño desacopla los componentes, asegurando que un componente lento o que falle no bloquee a los demás y permitiendo un flujo de datos seguro entre las tareas.

## **Sección 2: Componente Oyente de WhatsApp (Listeners)**

Este componente es responsable de interactuar con WhatsApp Web para leer mensajes entrantes y enviar respuestas. Se implementará utilizando una biblioteca de automatización de navegador directa para un control máximo.

### **Opción A: Implementación con Selenium**

Selenium es el estándar de la industria para la automatización de navegadores, respaldado por una vasta comunidad y documentación.3

* **Gestión de Sesiones Múltiples y Persistentes:** Para evitar la necesidad de escanear el código QR en cada ejecución, se utilizarán perfiles de navegador persistentes. Esto se logra configurando las ChromeOptions para que cada instancia del WebDriver utilice un directorio de perfil de usuario específico y separado.6  
  Python  
  from selenium import webdriver

  \# \--- Configuración para la Cuenta 1 \---  
  options1 \= webdriver.ChromeOptions()  
  \# Ruta al directorio de datos de usuario de Chrome  
  options1.add\_argument("user-data-dir=/ruta/a/datos/de/usuario/chrome")   
  \# Nombre del perfil específico  
  options1.add\_argument("profile-directory=Profile 1")   
  driver1 \= webdriver.Chrome(options=options1)  
  driver1.get('https://web.whatsapp.com')

  \# \--- Configuración para la Cuenta 2 \---  
  options2 \= webdriver.ChromeOptions()  
  options2.add\_argument("user-data-dir=/ruta/a/datos/de/usuario/chrome")  
  options2.add\_argument("profile-directory=Profile 2")  
  driver2 \= webdriver.Chrome(options=options2)  
  driver2.get('https://web.whatsapp.com')

### **Opción B: Implementación con Playwright**

Playwright es una alternativa moderna que a menudo ofrece mayor velocidad y fiabilidad, con una API asíncrona nativa que se integra perfectamente con asyncio.1

* **Gestión de Sesiones Múltiples y Persistentes:** Playwright simplifica la gestión de sesiones a través de "contextos de navegador persistentes". Se especifica un directorio donde se guardarán los datos de la sesión (cookies, almacenamiento local), y Playwright se encarga de reutilizarlos en ejecuciones posteriores.  
  Python  
  from playwright.async\_api import async\_playwright

  async def setup\_playwright\_sessions():  
      async with async\_playwright() as p:  
          \# \--- Configuración para la Cuenta 1 \---  
          context1 \= await p.chromium.launch\_persistent\_context(  
              user\_data\_dir="/ruta/a/tu/perfil/playwright/1",  
              headless=False  
          )  
          page1 \= await context1.new\_page()  
          await page1.goto('https://web.whatsapp.com')

          \# \--- Configuración para la Cuenta 2 \---  
          context2 \= await p.chromium.launch\_persistent\_context(  
              user\_data\_dir="/ruta/a/tu/perfil/playwright/2",  
              headless=False  
          )  
          page2 \= await context2.new\_page()  
          await page2.goto('https://web.whatsapp.com')

          \# Devolver page1, page2 para su uso en las tareas de asyncio  
          return page1, page2

### **Estrategia de Localización de Elementos**

La principal fragilidad de este enfoque es la dependencia de la estructura del DOM de WhatsApp Web. Para mitigar esto, la estrategia de localización de elementos se centrará en selectores estables, como los atributos title o aria-label, en lugar de clases CSS generadas automáticamente que pueden cambiar con frecuencia.1

## **Sección 3: Componente Relé de Telegram (Bot)**

La interacción con Telegram se realizará a través de su API de bots, que es robusta y está bien documentada.8

* **Biblioteca Recomendada:** Se utilizará **aiogram**, un framework moderno y asíncrono para la API de bots de Telegram, que se alinea perfectamente con la arquitectura general del proyecto.  
* **Configuración Inicial:**  
  1. Crear un nuevo bot a través de una conversación con @BotFather en Telegram para obtener el token de la API.9  
  2. Instalar la biblioteca aiogram (pip install aiogram).  
  3. Configurar el Dispatcher de aiogram para manejar las actualizaciones entrantes. Se definirán "handlers" específicos para procesar las respuestas del usuario y los comandos de control del bot.

## **Sección 4: Lógica del Puente e Integración**

El script principal orquestará la inicialización de los componentes y la gestión del flujo de mensajes.

* **Estructura del Código Principal:**  
  Python  
  import asyncio

  async def whatsapp\_listener(page\_or\_driver, account\_name, telegram\_queue):  
      \# Lógica para buscar nuevos mensajes en WhatsApp.  
      \# Al encontrar un mensaje, se formatea y se encola.  
      \# await telegram\_queue.put({'account': account\_name, 'sender': sender, 'text': message\_text})  
      pass

  async def telegram\_bot\_main(telegram\_queue, whatsapp\_queues):  
      \# Inicialización del bot de aiogram.  
      \# Tarea para leer de telegram\_queue y enviar mensajes a Telegram.  
      \# Handlers para recibir respuestas y encolarlas en la whatsapp\_queue apropiada.  
      pass

  async def main():  
      \# Inicializar drivers/contexts para ambas cuentas de WhatsApp.  
      telegram\_queue \= asyncio.Queue()  
      whatsapp\_queues \= {'WhatsApp-1': asyncio.Queue(), 'WhatsApp-2': asyncio.Queue()}

      \# Crear y ejecutar las tareas concurrentemente.  
      task1 \= asyncio.create\_task(whatsapp\_listener(driver1, "WhatsApp-1", telegram\_queue))  
      task2 \= asyncio.create\_task(whatsapp\_listener(driver2, "WhatsApp-2", telegram\_queue))  
      task3 \= asyncio.create\_task(telegram\_bot\_main(telegram\_queue, whatsapp\_queues))

      await asyncio.gather(task1, task2, task3)

  if \_\_name\_\_ \== "\_\_main\_\_":  
      asyncio.run(main())

* **Gestión de Estado para Respuestas:** Para enrutar correctamente las respuestas desde Telegram al chat de WhatsApp de origen, se implementará un sistema de mapeo de estado. Se utilizará un diccionario de Python para asociar el message\_id de cada mensaje reenviado a Telegram con una tupla que contenga la cuenta de WhatsApp de origen y el identificador del chat (chat\_id). Cuando el usuario responda a un mensaje en Telegram, el bot usará este mapa para dirigir la respuesta a la instancia de navegador y al chat correctos.

## **Sección 5: Consideraciones Finales**

Aunque este plan es técnicamente sólido, es crucial recordar los riesgos inherentes:

* **Fragilidad:** La solución dependerá de la estructura de la interfaz de usuario de WhatsApp Web, que puede cambiar sin previo aviso, requiriendo mantenimiento y actualizaciones del código.  
* **Seguridad:** El puente, por su naturaleza, rompe el cifrado de extremo a extremo, ya que debe descifrar los mensajes para poder reenviarlos. La seguridad de las comunicaciones dependerá de la seguridad de la máquina que ejecuta el script.14

Este proyecto representa un desafío de ingeniería avanzado que proporciona un control total sobre el flujo de mensajería, pero debe ser abordado con plena conciencia de sus limitaciones y riesgos operativos.

#### **Works cited**

1. How to APIfy WhatsApp \- Programmatic interaction with WhatsApp from Node using Playwright \- AMIS Technology Blog, accessed August 23, 2025, [https://technology.amis.nl/languages/node-js/how-to-apify-whatsapp-programmatic-interaction-with-whatsapp-from-node-using-playwright/](https://technology.amis.nl/languages/node-js/how-to-apify-whatsapp-programmatic-interaction-with-whatsapp-from-node-using-playwright/)  
2. open-wa/wa-automate-python: The most advanced Python whatsapp library for chatbots with advanced features. Be sure to this repository for updates\! \- GitHub, accessed August 23, 2025, [https://github.com/open-wa/wa-automate-python](https://github.com/open-wa/wa-automate-python)  
3. selvamaramaei/whatsapp-web-automation \- GitHub, accessed August 23, 2025, [https://github.com/selvamaramaei/whatsapp-web-automation](https://github.com/selvamaramaei/whatsapp-web-automation)  
4. whatsapp-selenium · GitHub Topics, accessed August 23, 2025, [https://github.com/topics/whatsapp-selenium](https://github.com/topics/whatsapp-selenium)  
5. whatsapp-auto-messaging · GitHub Topics, accessed August 23, 2025, [https://github.com/topics/whatsapp-auto-messaging](https://github.com/topics/whatsapp-auto-messaging)  
6. How to Open Multiple WhatsApp Web Accounts on One Computer at ..., accessed August 23, 2025, [https://wadesk.io/en/tutorial/how-to-open-multiple-whatsapp-web-accounts](https://wadesk.io/en/tutorial/how-to-open-multiple-whatsapp-web-accounts)  
7. How to Open Multiple WhatsApp Web Accounts on One Computer at the Same Time and Avoid Being Blocked？ \- WADesk, accessed August 23, 2025, [https://wadesk.io/blog-en/WhatsApp-multi-open-anti-ban](https://wadesk.io/blog-en/WhatsApp-multi-open-anti-ban)  
8. Telegram Bot API \- Telegram APIs, accessed August 23, 2025, [https://core.telegram.org/bots/api](https://core.telegram.org/bots/api)  
9. From BotFather to 'Hello World' \- Telegram APIs, accessed August 23, 2025, [https://core.telegram.org/bots/tutorial](https://core.telegram.org/bots/tutorial)  
10. How to Create a Bot for Telegram \- Short and Simple Guide for Beginners \- Flow XO, accessed August 23, 2025, [https://flowxo.com/how-to-create-a-bot-for-telegram-short-and-simple-guide-for-beginners/](https://flowxo.com/how-to-create-a-bot-for-telegram-short-and-simple-guide-for-beginners/)  
11. How to Create a Telegram Bot With No Coding? | Directual.com, accessed August 23, 2025, [https://www.directual.com/lesson-library/how-to-create-a-telegram-bot](https://www.directual.com/lesson-library/how-to-create-a-telegram-bot)  
12. Unauthorized use of automated or bulk messaging on WhatsApp, accessed August 23, 2025, [https://faq.whatsapp.com/5957850900902049](https://faq.whatsapp.com/5957850900902049)  
13. WhatsApp Terms of Service, accessed August 23, 2025, [https://www.whatsapp.com/legal/terms-of-service](https://www.whatsapp.com/legal/terms-of-service)  
14. Is it safe to message other apps from WhatsApp? | Kaspersky official blog, accessed August 23, 2025, [https://www.kaspersky.com.au/blog/whatsapp-interop-other-messengers-risks/33498/](https://www.kaspersky.com.au/blog/whatsapp-interop-other-messengers-risks/33498/)  
15. Element One – All of Matrix, WhatsApp, Signal and Telegram in one place | Hacker News, accessed August 23, 2025, [https://news.ycombinator.com/item?id=28997898](https://news.ycombinator.com/item?id=28997898)