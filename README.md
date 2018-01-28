# tripadvparser

tripadvparser - парсер отелей сайта tripadvisor. **Последнее обновление 20.07.17**.

## Требования
* Python 3
* PyYAML

## Использование

python tripadvisor.py команда, где команда:
* fetch_hotels - добавление отелей в БД
* fetch_photos - закачка фото по отелям, которые уже есть в БД
* fetch_prices - обновление цен по отелям, которые уже есть в БД
* clean - удаление БД и фоток

conf.yaml - конфигурационный файл.

Результат работы по умолчанию находится в директории output.

output/tripadvisor.db - БД.

output/errors.log - лог с ошибками.

http://sqlitebrowser.org/ - клиент для просмотра БД.
