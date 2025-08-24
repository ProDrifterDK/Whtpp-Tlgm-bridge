

# **Hoja de Ruta de Desarrollo: Puente de Mensajería WhatsApp-Telegram**

## **Introducción**

Este documento establece los siguientes pasos para el desarrollo del puente de mensajería WhatsApp-Telegram. Habiendo completado con éxito la fase de arquitectura y prototipado, ahora contamos con una base de código robusta, eficiente y asíncrona. Las siguientes fases se centran en construir sobre esta base para implementar la funcionalidad completa, mejorar la fiabilidad y preparar la aplicación para un despliegue continuo.

---

### **Fase 0: Arquitectura y Prototipado (Completada)**

El trabajo realizado hasta la fecha ha establecido una arquitectura sólida utilizando asyncio, Playwright y aiogram. Los problemas críticos de diseño, como los bucles asíncronos en conflicto y la gestión ineficiente de recursos, han sido resueltos. La aplicación actual sirve como una base excelente para el desarrollo de características adicionales.

---

### **Fase 1: Implementar el Flujo Bidireccional de Mensajes de Texto**

El objetivo principal de esta fase es lograr que la comunicación de texto sea completamente funcional en ambas direcciones, convirtiendo el prototipo en una herramienta de comunicación útil.

#### **Paso 1.1: Implementar la Lógica de Envío de Respuestas a WhatsApp**

* **Objetivo:** Permitir que una respuesta enviada desde Telegram se entregue al chat correcto en la cuenta de WhatsApp correspondiente.  
* **Acciones Técnicas:**  
  1. **Crear Colas de Salida:** En la función main, instanciar dos colas asyncio.Queue adicionales, una para cada oyente de WhatsApp (ej. whatsapp\_1\_reply\_queue, whatsapp\_2\_reply\_queue).  
  2. **Modificar el Manejador de Telegram:** Dentro de la función handle\_message en telegram\_bot\_main, cuando se detecta una respuesta válida, se debe:  
     * Consultar el state\_map para identificar la cuenta de origen ('WhatsApp-1' o 'WhatsApp-2') y el chat original.  
     * Colocar un objeto de mensaje (ej. {'chat\_original': 'Nombre del Contacto', 'texto': message.text}) en la cola de salida apropiada.  
  3. **Modificar el Oyente de WhatsApp:** Cada función whatsapp\_listener debe ser actualizada para:  
     * Aceptar su cola de respuestas como un nuevo argumento.  
     * En cada iteración del bucle while True, comprobar de forma no bloqueante si hay un mensaje en su cola de respuestas.  
     * Si se encuentra un mensaje, ejecutar la secuencia de Playwright para buscar el chat por su nombre, escribir el texto de la respuesta en el cuadro de entrada y simular el clic en el botón de enviar.

#### **Paso 1.2: Refinar la Lógica de Lectura de Mensajes en WhatsApp**

* **Objetivo:** Mejorar la detección y extracción de mensajes para que sea más fiable y maneje múltiples chats.  
* **Acciones Técnicas:**  
  1. **Manejar Chats No Leídos:** Implementar una lógica en whatsapp\_listener que primero busque en la lista de chats los indicadores de mensajes no leídos.  
  2. **Cambio de Contexto de Chat:** Al detectar un chat no leído, el script debe simular un clic en ese chat para abrirlo antes de ejecutar la lógica existente de búsqueda de mensajes.  
  3. **Robustecer Selectores:** Mover los selectores de CSS/XPath a variables en la parte superior del script para facilitar su actualización en caso de que la interfaz de WhatsApp Web cambie.

---

### **Fase 2: Añadir Soporte para Multimedia y Mejorar la Robustez**

Con el flujo de texto funcionando, el enfoque se desplaza hacia el manejo de contenido más complejo y la mejora de la fiabilidad a largo plazo de la aplicación.

#### **Paso 2.1: Implementar el Reenvío de Archivos Multimedia**

* **Objetivo:** Permitir el reenvío de imágenes y documentos en ambas direcciones.  
* **Acciones Técnicas:**  
  * **De WhatsApp a Telegram:** El whatsapp\_listener deberá detectar si un nuevo mensaje contiene un elemento multimedia. Si es así, deberá descargar el archivo al disco local y luego usar el método apropiado de aiogram (bot.send\_photo o bot.send\_document) para subirlo a Telegram.  
  * **De Telegram a WhatsApp:** El handle\_message deberá detectar si una respuesta contiene un archivo adjunto. Si es así, deberá descargarlo localmente usando los métodos de aiogram y luego usar Playwright para interactuar con el botón de "adjuntar archivo" en WhatsApp Web, seleccionar el archivo descargado y enviarlo.

#### **Paso 2.2: Implementar Notificaciones de Estado y Manejo de Errores**

* **Objetivo:** Hacer que el bot sea más resistente a los fallos y que comunique su estado al usuario.  
* **Acciones Técnicas:**  
  1. **Detección de Desconexión:** Ampliar el bloque try/except en whatsapp\_listener para identificar errores específicos de Playwright que indiquen una sesión de WhatsApp cerrada o inválida.  
  2. **Notificaciones de Estado:** Al detectar un error crítico (como una desconexión), el whatsapp\_listener debe colocar un mensaje de estado especial en la message\_queue (ej. ('status', 'ERROR: La cuenta WhatsApp-1 se ha desconectado.')). El queue\_consumer en Telegram reenviará esta alerta al usuario, informándole de que se requiere una intervención manual.

---

### **Fase 3: Preparación para el Despliegue y Mantenimiento**

La fase final se centra en hacer que la aplicación sea fácil de configurar, desplegar y mantener de forma continua.

#### **Paso 3.1: Externalizar la Configuración**

* **Objetivo:** Separar la configuración del código para facilitar las modificaciones sin editar el script.  
* **Acciones Técnicas:**  
  * Crear un archivo de configuración externo (ej. .env o config.yaml).  
  * Mover todas las variables configurables (tokens de API, IDs de chat, rutas de perfiles, etc.) a este archivo.  
  * Utilizar una biblioteca como python-dotenv o PyYAML para cargar estos valores al inicio del script.

#### **Paso 3.2: Containerizar la Aplicación con Docker**

* **Objetivo:** Empaquetar la aplicación y sus dependencias en un contenedor portátil para un despliegue sencillo y consistente.  
* **Acciones Técnicas:**  
  1. **Crear un Dockerfile:** Utilizar la imagen oficial de Playwright para Python como base para asegurar que todas las dependencias del navegador estén presentes.  
  2. **Gestionar Dependencias:** Copiar un archivo requirements.txt e instalar las bibliotecas de Python necesarias.  
  3. **Configurar Volúmenes:** Al ejecutar el contenedor, utilizar volúmenes de Docker para mapear los directorios user\_data a una ubicación persistente en la máquina anfitriona. Esto es crucial para que las sesiones de WhatsApp se conserven entre reinicios del contenedor.1  
  4. **Comando de Ejecución:** Definir el CMD en el Dockerfile para ejecutar el script bridge.py.

#### **Works cited**

1. open-wa/wa-automate-python: The most advanced Python whatsapp library for chatbots with advanced features. Be sure to this repository for updates\! \- GitHub, accessed August 23, 2025, [https://github.com/open-wa/wa-automate-python](https://github.com/open-wa/wa-automate-python)