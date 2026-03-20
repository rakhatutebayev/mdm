# iDRAC6 Update Guide

Короткая памятка по обновлению `iDRAC6` на `Dell PowerEdge R710` до `2.92`.

## Что было проверено

- Сервер: `PowerEdge R710`
- Старая версия: `iDRAC 1.41 Build 13`
- Новая версия: `iDRAC 2.92 Build 05`
- Обновление прошло успешно через `TFTP + racadm fwupdate`

## Что потребуется

- доступ к `iDRAC` по `SSH`
- хост в той же сети, доступный для `iDRAC` по `TFTP`
- файл прошивки `firmimg.d6`
- пакет `tftpd-hpa`

Проверенный пакет Dell:

- `iDRAC6_2.92_A00_FW_IMG.exe`
- страница Dell: [Dell iDRAC Monolithic Release 2.92](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=kpccc)

## 1. Установить TFTP сервер

На Linux-хосте, который будет раздавать прошивку:

```bash
sudo apt-get install -y tftpd-hpa tftp-hpa
```

Проверить конфиг:

```bash
cat /etc/default/tftpd-hpa
```

Рабочий пример:

```bash
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/srv/tftp"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure"
```

Перезапустить сервис:

```bash
sudo systemctl restart tftpd-hpa
sudo systemctl status tftpd-hpa
```

## 2. Подготовить файл прошивки

Нужен именно файл:

```text
firmimg.d6
```

Разместить его, например, так:

```bash
sudo mkdir -p /srv/tftp/idrac6/2.92
sudo cp firmimg.d6 /srv/tftp/idrac6/2.92/firmimg.d6
sudo chmod 644 /srv/tftp/idrac6/2.92/firmimg.d6
```

## 3. Проверить TFTP локально

На TFTP-хосте:

```bash
printf 'get idrac6/2.92/firmimg.d6 /tmp/firmimg_test.d6\nquit\n' | tftp 127.0.0.1
ls -l /tmp/firmimg_test.d6
```

Если файл скачался, TFTP готов.

## 4. Подключиться к iDRAC по SSH

```bash
ssh root@192.168.11.219
```

## 5. Проверить текущую версию

```bash
racadm getsysinfo
```

Ищи строки:

```text
Firmware Version
Firmware Build
```

## 6. Запустить обновление

Проверенная команда:

```bash
racadm fwupdate -g -u -a 192.168.11.153 -d /idrac6/2.92
```

Где:

- `192.168.11.153` - IP TFTP-сервера
- `/idrac6/2.92` - каталог внутри `TFTP root`, где лежит `firmimg.d6`

## 7. Проверять статус обновления

```bash
racadm fwupdate -s
```

Пример нормального статуса:

```text
Firmware update in progress [30 percent complete]
```

## 8. Дождаться перезагрузки iDRAC

Во время обновления:

- `SSH` к iDRAC временно пропадет
- `HTTPS` к iDRAC временно пропадет
- сам сервер обычно не выключается

## 9. Проверить итоговую версию после возврата

```bash
racadm getsysinfo
```

Ожидаемый результат:

```text
Firmware Version        = 2.92
Firmware Build          = 05
```

## 10. Проверить, что функции работают

Если настроен SNMP trap:

```bash
racadm testtrap -i 1
```

После успешного обновления ожидаемый ответ:

```text
Test trap sent successfully
```

## Краткий сценарий

```bash
sudo apt-get install -y tftpd-hpa tftp-hpa
sudo mkdir -p /srv/tftp/idrac6/2.92
sudo cp firmimg.d6 /srv/tftp/idrac6/2.92/firmimg.d6
sudo chmod 644 /srv/tftp/idrac6/2.92/firmimg.d6
sudo systemctl restart tftpd-hpa

ssh root@192.168.11.219
racadm getsysinfo
racadm fwupdate -g -u -a 192.168.11.153 -d /idrac6/2.92
racadm fwupdate -s
racadm getsysinfo
racadm testtrap -i 1
```

## Важные замечания

- обновляется именно `iDRAC`, не `BIOS`
- на время обновления `iDRAC` будет временно недоступен
- если обновление стартовало, но версия не меняется, нужно дождаться полной перезагрузки `iDRAC`
- старая версия `1.41` слишком устаревшая, переход на `2.92` заметно улучшает стабильность
